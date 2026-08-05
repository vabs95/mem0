"""Tests for _platform.py's spawn_bg() optional log_path.

Regression coverage for a real observability gap: spawn_bg unconditionally
discarded a background task's stdout/stderr, so a spawned script like
auto_import.py could fail for any reason with zero trace anywhere. The
log_path parameter lets high-value callers (auto-import, one-shot setup
scripts) capture that output durably, while high-frequency low-value
callers (telemetry pings) can still omit it and stay silent.
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
