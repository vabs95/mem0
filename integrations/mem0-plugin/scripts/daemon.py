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
    if hook_name == "add_memory":
        text = (input_data.get("tool_input") or {}).get("text")
        return text[:200] if isinstance(text, str) and text else "Memory added"
    if hook_name == "post_tool_use":
        tool = input_data.get("tool_name")
        return f"Used {tool}" if tool else None
    return None


def _extract_added_memory_ids(tool_response) -> list[str]:
    """Pull memory ids out of an add_memory MCP tool's response.

    Handles the response already being the JSON string server.py's
    _json_call returns (``{"results": [{"id": ..., "event": "ADD"}]}``),
    or having been unwrapped/re-wrapped by the calling editor's hook
    payload into an MCP content-block shape (``{"content": [{"type":
    "text", "text": "<same JSON string>"}]}``). Best-effort: any shape it
    doesn't recognize just yields no ids, never raises (caller already
    wraps this in a broad try/except).
    """
    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(tool_response, dict):
        content = tool_response.get("content")
        if isinstance(content, list):
            for block in content:
                text = block.get("text") if isinstance(block, dict) else None
                if isinstance(text, str):
                    try:
                        tool_response = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    break
    if not isinstance(tool_response, dict):
        return []
    results = tool_response.get("results")
    if not isinstance(results, list):
        return []
    return [r["id"] for r in results if isinstance(r, dict) and r.get("id") and r.get("event") != "NONE"]


def _build_timeline_body(hook_name: str, input_data: dict) -> dict | None:
    """Synchronously resolve everything env/cache-dependent for a timeline
    event. Must be called while still holding _dispatch_lock, i.e. before
    any other request's _apply_request_env can run.

    This daemon is a single process shared by every editor on the machine
    (Claude Code, Codex, ...) — os.environ and the cached identity
    resolvers are process-global, mutable state. Reading them from a
    detached background thread *after* the lock is released is racy: a
    concurrent request from a different platform can overwrite
    MEM0_PLATFORM/MEM0_USER_ID/etc. in the window between this request's
    dispatch and a background thread getting scheduled to read them,
    misattributing the event (e.g. a Codex hook's event logged with
    source_agent "claude-code" because a Claude Code hook fired around the
    same time and its request didn't carry MEM0_PLATFORM). Resolving
    everything here, synchronously, while the lock is held, and handing
    the background thread a plain dict with no further env reads closes
    that window. Returns None when there's no API key (nothing to post).
    """
    api_key = _handlers.resolve_api_key()
    if not api_key:
        return None

    category = None
    memory_ids: list[str] = []
    event_type = hook_name
    # An add_memory tool call arrives here as a generic post_tool_use
    # hook — reclassify it to its own event_type and attach the
    # provenance link (which memories this event produced) and the
    # caller's own metadata.type classification (decision/bug_fix/...,
    # set in _handlers.py's cmd_enforce_metadata), claude-mem-style.
    if hook_name == "post_tool_use" and (input_data.get("tool_name") or "").endswith("__add_memory"):
        event_type = "add_memory"
        memory_ids = _extract_added_memory_ids(input_data.get("tool_response"))
        category = (input_data.get("tool_input") or {}).get("metadata", {}).get("type")

    cwd = input_data.get("cwd")
    return {
        "event_type": event_type,
        "source_agent": os.environ.get("MEM0_PLATFORM", "claude-code"),
        "user_id": _handlers.resolve_user_id(),
        "project": _handlers.resolve_project_id(cwd),
        "summary": _summarize_event(event_type, input_data),
        "category": category,
        "memory_ids": memory_ids,
        "_api_key": api_key,
    }


def _send_timeline_event(body: dict) -> None:
    """Best-effort, fire-and-forget POST of an already-resolved timeline
    event body — pure network I/O, no env/cache reads, so it's safe to run
    from a detached background thread regardless of what other requests do
    to the daemon's process-global identity state in the meantime. Never
    allowed to affect the hook's own stdout/exit code; any failure here is
    swallowed and logged, nothing more."""
    try:
        from _api import api_base_url, auth_headers
        import urllib.request

        api_key = body.pop("_api_key")
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", **auth_headers(api_key)}
        req = urllib.request.Request(f"{api_base_url()}/timeline/events", data=data, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=3).close()
    except Exception as exc:
        _log(f"timeline write failed: {exc}")


def _run_captured(hook_name: str, input_data: dict, env_overrides: dict) -> tuple[str, int]:
    """Apply this request's identity env, run its hook handler, and build
    its timeline-event body, all atomically under _dispatch_lock.

    Serialized behind _dispatch_lock: the handlers do local file I/O on
    shared per-user state (session stats, message counters) that was
    never written to expect concurrent callers, and hook events aren't
    high-frequency enough for serializing them to matter. Applying the
    per-request identity env override and building the timeline body in
    the same locked region (rather than the previous per-call lock plus a
    separately-scheduled background read) is what actually closes the
    cross-platform misattribution race — see _build_timeline_body's
    docstring.
    """
    with _dispatch_lock:
        env_changed = _apply_request_env(env_overrides)
        if hook_name == "session_start" or env_changed:
            _invalidate_cache()

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

        timeline_body = _build_timeline_body(hook_name, input_data)

    if timeline_body is not None:
        threading.Thread(target=_send_timeline_event, args=(timeline_body,), daemon=True).start()
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

        env_overrides = input_data.pop("_env", None) or {}
        stdout, exit_code = _run_captured(hook_name, input_data, env_overrides)
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
