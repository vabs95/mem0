"""OS-specific process helpers, isolated to this one module.

Every other script in this plugin (``_handlers.py`` and, eventually, the
warm daemon) must go through these functions rather than branching on
``sys.platform`` itself — this is what keeps hook logic identical across
Claude Code, Codex, Windows, macOS, and Linux instead of forking into
parallel per-OS implementations.
"""

from __future__ import annotations

import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

# CREATE_NO_WINDOW — suppresses the console window Windows would otherwise
# briefly flash for each backgrounded subprocess.
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def spawn_bg(args: list[str], log_path: str | None = None, cwd: str | None = None) -> None:
    """Launch ``args`` as a detached, fire-and-forget background process.

    ``log_path``, when given, appends the child's stdout+stderr there
    instead of discarding them — pass it for anything whose silent
    failure would be hard to notice (auto-import, one-shot setup
    scripts). Omit it (the default) for high-frequency, low-value
    background pings (telemetry, session stats) where a log entry per
    call would just be noise. Either way this call itself never raises;
    a background task's own failure is still that task's problem, not
    the caller's.

    ``cwd``, when given, sets the child's actual working directory. This
    matters a lot when the caller is the daemon (see daemon.py): every
    spawn_bg call made from inside a hook handler runs in the daemon's
    own process, so *without* an explicit cwd the child inherits the
    daemon's cwd — frozen at whatever directory happened to spawn the
    daemon in the first place, not the current hook invocation's actual
    working directory. A script that resolves its project id from
    os.getcwd() (directly, or via resolve_project_id(cwd=None)) would
    then silently resolve against the wrong project. Always pass the
    hook's own cwd (input_data.get("cwd")) here for anything
    project-scoped.
    """
    try:
        stdout = stderr = subprocess.DEVNULL
        _log_file = None
        if log_path is not None:
            _log_file = open(log_path, "a")
            stdout = stderr = _log_file
        try:
            if IS_WINDOWS:
                subprocess.Popen(args, creationflags=_CREATE_NO_WINDOW, stdout=stdout, stderr=stderr, cwd=cwd)
            else:
                subprocess.Popen(args, stdout=stdout, stderr=stderr, cwd=cwd)
        finally:
            if _log_file is not None:
                _log_file.close()
    except Exception:
        pass


def spawn_daemon_detached(args: list[str], log_path: str) -> None:
    """Launch ``args`` as a fully detached background daemon.

    Survives the parent hook process exiting, on every OS. On POSIX,
    ``start_new_session=True`` detaches from the controlling terminal. On
    Windows, plain ``detached`` doesn't fully daemonize (see claude-mem's
    ProcessManager.spawnDaemon, which hit the same limitation), so we add
    DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP creation flags instead.

    Explicitly pins cwd to the directory containing ``args[-1]`` (the
    script being launched — daemon.py) rather than leaving it to inherit
    whatever directory the *first* hook invocation that happened to spawn
    the daemon was running in. The daemon is a shared, long-lived process
    across every project a caller might be in; anything downstream that
    falls back to the daemon's own os.getcwd() (a bare
    resolve_project_id() with no cwd passed, for instance) should get a
    stable, predictable value — not whichever project's session happened
    to spawn the daemon first.
    """
    try:
        with open(log_path, "a") as log:
            daemon_dir = os.path.dirname(os.path.abspath(args[-1])) if args else None
            if IS_WINDOWS:
                subprocess.Popen(
                    args,
                    creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
                    cwd=daemon_dir,
                )
            else:
                subprocess.Popen(
                    args,
                    start_new_session=True,
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
                    cwd=daemon_dir,
                )
    except Exception:
        pass


def is_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is currently running."""
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=_CREATE_NO_WINDOW,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
