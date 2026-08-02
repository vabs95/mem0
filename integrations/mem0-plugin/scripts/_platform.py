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


def spawn_bg(args: list[str]) -> None:
    """Launch ``args`` as a detached, fire-and-forget background process."""
    try:
        if IS_WINDOWS:
            subprocess.Popen(args, creationflags=_CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def spawn_daemon_detached(args: list[str], log_path: str) -> None:
    """Launch ``args`` as a fully detached background daemon.

    Survives the parent hook process exiting, on every OS. On POSIX,
    ``start_new_session=True`` detaches from the controlling terminal. On
    Windows, plain ``detached`` doesn't fully daemonize (see claude-mem's
    ProcessManager.spawnDaemon, which hit the same limitation), so we add
    DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP creation flags instead.
    """
    try:
        with open(log_path, "a") as log:
            if IS_WINDOWS:
                subprocess.Popen(
                    args,
                    creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    args,
                    start_new_session=True,
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
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
