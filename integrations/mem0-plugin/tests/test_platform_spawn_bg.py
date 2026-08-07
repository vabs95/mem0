"""Tests for _platform.py's spawn_bg() optional log_path and cwd.

Regression coverage for two real bugs:

1. Observability gap: spawn_bg unconditionally discarded a background
   task's stdout/stderr, so a spawned script like auto_import.py could
   fail for any reason with zero trace anywhere. log_path lets high-value
   callers (auto-import, one-shot setup scripts) capture that output
   durably, while high-frequency low-value callers (telemetry pings) can
   still omit it and stay silent.

2. Wrong-project data corruption: every spawn_bg call made from inside a
   hook handler runs in the *daemon's* process, so without an explicit
   cwd the spawned child (auto_import.py, auto_capture.py) inherited the
   daemon's own frozen cwd — wherever it happened to be spawned from —
   instead of the actual hook invocation's cwd. In production this
   imported one project's AGENTS.md into another project's memory scope.
   cwd now gets threaded through explicitly.
"""

from __future__ import annotations

import sys
import time


def test_spawn_bg_without_log_path_still_runs_the_child(tmp_path):
    """Default (no log_path) behavior is unchanged: output goes to
    DEVNULL, but the child process still runs to completion."""
    from _platform import spawn_bg

    marker = tmp_path / "ran.txt"
    spawn_bg([sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"])

    deadline = time.time() + 3
    while time.time() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.exists()


def test_spawn_bg_with_log_path_captures_stdout_and_stderr(tmp_path):
    from _platform import spawn_bg

    log_path = tmp_path / "background.log"
    script = (
        "import sys; "
        "print('stdout line'); "
        "print('stderr line', file=sys.stderr)"
    )
    spawn_bg([sys.executable, "-c", script], log_path=str(log_path))

    deadline = time.time() + 3
    content = ""
    while time.time() < deadline:
        if log_path.exists():
            content = log_path.read_text()
            if "stdout line" in content and "stderr line" in content:
                break
        time.sleep(0.05)

    assert "stdout line" in content
    assert "stderr line" in content


def test_spawn_bg_with_log_path_appends_across_calls(tmp_path):
    from _platform import spawn_bg

    log_path = tmp_path / "background.log"
    spawn_bg([sys.executable, "-c", "print('first')"], log_path=str(log_path))
    time.sleep(0.3)
    spawn_bg([sys.executable, "-c", "print('second')"], log_path=str(log_path))
    time.sleep(0.3)

    content = log_path.read_text()
    assert "first" in content
    assert "second" in content


def test_spawn_bg_never_raises_on_bad_args():
    from _platform import spawn_bg

    # Nonexistent executable — Popen itself would raise; spawn_bg must
    # swallow it (it's fire-and-forget by design, callers never check
    # for a launch failure).
    spawn_bg(["/nonexistent/binary/path", "--flag"])
    spawn_bg(["/nonexistent/binary/path", "--flag"], log_path="/nonexistent/dir/log.txt")


def test_spawn_bg_sets_child_working_directory(tmp_path):
    """The core regression test: the child's actual os.getcwd() must be
    the passed cwd, not the calling (daemon) process's own directory —
    this is what a bare resolve_project_id() (no explicit cwd arg, as
    auto_capture.py calls it) resolves against."""
    from _platform import spawn_bg

    target_dir = tmp_path / "some-project"
    target_dir.mkdir()
    out_file = tmp_path / "cwd_seen.txt"

    spawn_bg(
        [sys.executable, "-c", f"import os; open({str(out_file)!r}, 'w').write(os.getcwd())"],
        cwd=str(target_dir),
    )

    deadline = time.time() + 3
    while time.time() < deadline and not out_file.exists():
        time.sleep(0.05)

    assert out_file.exists()
    import os as _os

    assert _os.path.realpath(out_file.read_text()) == _os.path.realpath(str(target_dir))


def test_spawn_bg_without_cwd_inherits_caller_directory(tmp_path):
    """Confirms the bug this fixes: omitting cwd means the child inherits
    whatever directory spawn_bg's own caller was in."""
    import os as _os

    from _platform import spawn_bg

    out_file = tmp_path / "cwd_seen.txt"
    spawn_bg([sys.executable, "-c", f"import os; open({str(out_file)!r}, 'w').write(os.getcwd())"])

    deadline = time.time() + 3
    while time.time() < deadline and not out_file.exists():
        time.sleep(0.05)

    assert out_file.exists()
    assert _os.path.realpath(out_file.read_text()) == _os.path.realpath(_os.getcwd())


def test_spawn_daemon_detached_pins_cwd_to_the_daemon_scripts_dir(tmp_path):
    """spawn_daemon_detached must not let the daemon inherit whichever
    project's session happened to spawn it first — it pins cwd to the
    directory containing the daemon script itself."""
    import os as _os

    from _platform import spawn_daemon_detached

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    out_file = tmp_path / "daemon_cwd_seen.txt"
    fake_daemon = scripts_dir / "fake_daemon.py"
    fake_daemon.write_text(f"import os; open({str(out_file)!r}, 'w').write(os.getcwd())\n")
    log_path = tmp_path / "daemon.log"

    spawn_daemon_detached([sys.executable, str(fake_daemon)], str(log_path))

    deadline = time.time() + 3
    while time.time() < deadline and not out_file.exists():
        time.sleep(0.05)

    assert out_file.exists()
    assert _os.path.realpath(out_file.read_text()) == _os.path.realpath(str(scripts_dir))
