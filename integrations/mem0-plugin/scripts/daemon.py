"""Local warm daemon for mem0 hook dispatch.

Replaces the "spawn a fresh Python interpreter per hook event" pattern with
a single, long-lived process that hook invocations talk to over plain
HTTP/TCP on localhost — the same transport on every OS (POSIX and
Windows), deliberately, to avoid the Unix-socket-vs-named-pipe split that
would otherwise fork this code per platform.

Not a full supervisor: no persistent watchdog process babysits this one.
Self-healing instead happens on the client side — every hook invocation
that can't reach the daemon just spawns a new one (see
``_handlers.py``'s ``_dispatch_via_daemon``) — and the daemon shuts itself
down after a period of inactivity so nothing lingers across a sleep/wake
cycle or an editor restart.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import _handlers  # noqa: E402
from _platform import IS_WINDOWS  # noqa: E402

STATE_DIR = os.path.expanduser("~/.mem0")
PORT_FILE = os.path.join(STATE_DIR, "daemon.port")
PID_FILE = os.path.join(STATE_DIR, "daemon.pid")
LOG_FILE = os.path.join(STATE_DIR, "daemon.log")

IDLE_SHUTDOWN_SECONDS = 30 * 60
CACHE_TTL_SECONDS = 45

# Identity env vars the daemon resolves on behalf of callers. The daemon is a
# long-lived process, so its own os.environ is frozen at whatever it looked
# like when the daemon was spawned — a caller exporting MEM0_USER_ID in a
# fresh shell afterwards would otherwise never be seen without killing and
# respawning the daemon. Callers (freshly spawned per hook invocation, so
# they always see current env) forward their own values for these keys in
# the request body; _apply_request_env applies them for the duration of
# that one request and restores the daemon's own startup values after.
_IDENTITY_ENV_KEYS = ("MEM0_USER_ID", "MEM0_PROJECT_ID", "MEM0_API_KEY", "MEM0_AGENT_ID", "MEM0_PLATFORM")
_STARTUP_ENV = {k: os.environ[k] for k in _IDENTITY_ENV_KEYS if k in os.environ}


def _apply_request_env(overrides: dict) -> bool:
    """Set identity env vars from a request, falling back to the daemon's
    own startup values for any key the request didn't supply — so one
    caller's identity never leaks into the next request's resolution.

    Returns True if any key actually changed value, so the caller only
    pays for a cache invalidation (subprocess/file-read re-resolution)
    when the identity picture genuinely differs from last time — not on
    every single hook event, which would defeat the point of caching."""
    changed = False
    for key in _IDENTITY_ENV_KEYS:
        value = overrides.get(key) if isinstance(overrides, dict) else None
        new_value = value or _STARTUP_ENV.get(key)
        if os.environ.get(key) != new_value:
            changed = True
        if new_value:
            os.environ[key] = new_value
        else:
            os.environ.pop(key, None)
    return changed

_dispatch_lock = threading.Lock()
_last_request_at = time.time()
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _log(message: str) -> None:
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        pass


def _cached(key: str, compute):
    """TTL-cached wrapper around a zero-arg resolver.

    _identity.py/_project.py stay stateless and independently testable —
    caching lives here, in the one process that actually calls them often
    enough for the repeated disk/subprocess reads to matter.
    """
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    value = compute()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _invalidate_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _install_caching() -> None:
    """Wrap the identity/project resolvers _handlers.py already imported
    with cached versions, without touching _identity.py/_project.py."""
    real_resolve_api_key = _handlers.resolve_api_key
    real_resolve_user_id = _handlers.resolve_user_id
    real_resolve_project_id = _handlers.resolve_project_id
    real_resolve_branch = _handlers.resolve_branch

    _handlers.resolve_api_key = lambda: _cached("api_key", real_resolve_api_key)
    _handlers.resolve_user_id = lambda: _cached("user_id", real_resolve_user_id)
    _handlers.resolve_project_id = lambda cwd=None: _cached(f"project_id:{cwd}", lambda: real_resolve_project_id(cwd))
    _handlers.resolve_branch = lambda cwd=None: _cached(f"branch:{cwd}", lambda: real_resolve_branch(cwd))


def _summarize_event(hook_name: str, input_data: dict) -> str | None:
    """Short human-readable description of what happened, for the timeline
    UI — without this every row renders with an empty summary column."""
    if hook_name == "user_prompt":
        prompt = (input_data.get("prompt") or "").strip()
        return prompt[:200] if prompt else None
    if hook_name == "session_start":
        return f"Session {input_data.get('source') or 'startup'}"
    if hook_name == "stop":
        return "Session ended"
    if hook_name == "pre_compact":
        return "Context compacted"
    if hook_name == "post_tool_use":
        tool = input_data.get("tool_name")
        return f"Used {tool}" if tool else None
    return None


def _post_timeline_event(hook_name: str, input_data: dict) -> None:
    """Best-effort, fire-and-forget write to the server-side timeline.

    Never allowed to affect the hook's own stdout/exit code — any failure
    here is swallowed and logged, nothing more.
    """
    try:
        from _api import api_base_url, auth_headers
        import urllib.request

        api_key = _handlers.resolve_api_key()
        if not api_key:
            return
        cwd = input_data.get("cwd")
        body = {
            "event_type": hook_name,
            "source_agent": os.environ.get("MEM0_PLATFORM", "claude-code"),
            "user_id": _handlers.resolve_user_id(),
            "project": _handlers.resolve_project_id(cwd),
            "summary": _summarize_event(hook_name, input_data),
        }
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", **auth_headers(api_key)}
        req = urllib.request.Request(f"{api_base_url()}/timeline/events", data=data, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=3).close()
    except Exception as exc:
        _log(f"timeline write failed: {exc}")


def _run_captured(hook_name: str, input_data: dict) -> tuple[str, int]:
    """Run a hook handler in-process, capturing its stdout/exit code.

    Serialized behind _dispatch_lock: the handlers do local file I/O on
    shared per-user state (session stats, message counters) that was
    never written to expect concurrent callers, and hook events aren't
    high-frequency enough for serializing them to matter.
    """
    with _dispatch_lock:
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        exit_code = 0
        try:
            _handlers.dispatch(hook_name, input_data)
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except Exception as exc:
            _log(f"handler {hook_name} raised: {exc}")
            exit_code = 1
        finally:
            sys.stdout = old_stdout
        stdout = buf.getvalue()

    threading.Thread(target=_post_timeline_event, args=(hook_name, input_data), daemon=True).start()
    return stdout, exit_code


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        _log(format % args)

    def do_GET(self):
        global _last_request_at
        _last_request_at = time.time()
        if self.path == "/health":
            self._json_response(200, {"pid": os.getpid(), "started_at": _STARTED_AT})
        else:
            self._json_response(404, {"error": "not_found"})

    def do_POST(self):
        global _last_request_at
        _last_request_at = time.time()
        if not self.path.startswith("/hook/"):
            self._json_response(404, {"error": "not_found"})
            return
        hook_name = self.path[len("/hook/"):]
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            input_data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            input_data = {}

        env_overrides = input_data.pop("_env", None)
        env_changed = _apply_request_env(env_overrides or {})
        if hook_name == "session_start" or env_changed:
            _invalidate_cache()

        stdout, exit_code = _run_captured(hook_name, input_data)
        self._json_response(200, {"stdout": stdout, "exit_code": exit_code})

    def _json_response(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _idle_watchdog(server: ThreadingHTTPServer) -> None:
    while True:
        time.sleep(60)
        if time.time() - _last_request_at > IDLE_SHUTDOWN_SECONDS:
            _log("idle timeout reached, shutting down")
            _cleanup_state_files()
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


def _cleanup_state_files() -> None:
    for path in (PORT_FILE, PID_FILE):
        try:
            os.remove(path)
        except OSError:
            pass


def main() -> None:
    global _STARTED_AT
    os.makedirs(STATE_DIR, exist_ok=True)

    _install_caching()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    _STARTED_AT = time.time()

    with open(PORT_FILE, "w") as f:
        f.write(str(port))
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    _log(f"daemon started pid={os.getpid()} port={port} windows={IS_WINDOWS}")

    watchdog = threading.Thread(target=_idle_watchdog, args=(server,), daemon=True)
    watchdog.start()

    try:
        server.serve_forever()
    finally:
        _cleanup_state_files()
        _log("daemon stopped")


if __name__ == "__main__":
    main()
