"""Tests for the daemon's self-recycling watchdog (daemon.py).

Regression coverage for a real usability gap: previously, any code
change to the plugin's scripts (a `codex plugin add` cache refresh, a
git pull, a manual edit) required someone to notice the daemon was
running stale code and manually find+kill it — otherwise it would keep
serving hook dispatches with whatever logic it loaded at startup,
silently, indefinitely. _watchdog now compares a cheap fingerprint of
SCRIPT_DIR's .py files against what was loaded at startup and retires
the daemon once they diverge, letting the client's existing
spawn-on-demand self-healing bring up a fresh one automatically.
"""

from __future__ import annotations

import os


def test_fingerprint_changes_when_a_script_file_changes(monkeypatch, tmp_path):
    import daemon

    monkeypatch.setattr(daemon, "SCRIPT_DIR", str(tmp_path))
    script = tmp_path / "_handlers.py"
    script.write_text("x = 1\n")

    before = daemon._compute_code_fingerprint()

    # Force a distinct mtime — some filesystems have coarse mtime
    # resolution, so bump it explicitly rather than relying on real time
    # passing between the two writes.
    new_time = os.path.getmtime(script) + 5
    script.write_text("x = 2\n")
    os.utime(script, (new_time, new_time))

    after = daemon._compute_code_fingerprint()
    assert before != after


def test_fingerprint_stable_when_nothing_changes(monkeypatch, tmp_path):
    import daemon

    monkeypatch.setattr(daemon, "SCRIPT_DIR", str(tmp_path))
    (tmp_path / "daemon.py").write_text("x = 1\n")
    (tmp_path / "_handlers.py").write_text("y = 2\n")

    first = daemon._compute_code_fingerprint()
    second = daemon._compute_code_fingerprint()
    assert first == second


def test_fingerprint_ignores_non_python_files(monkeypatch, tmp_path):
    import daemon

    monkeypatch.setattr(daemon, "SCRIPT_DIR", str(tmp_path))
    (tmp_path / "daemon.py").write_text("x = 1\n")
    before = daemon._compute_code_fingerprint()

    (tmp_path / "hooks.json").write_text('{"changed": true}\n')
    after = daemon._compute_code_fingerprint()
    assert before == after


def test_watchdog_shuts_down_when_source_changes(monkeypatch, tmp_path):
    """The core regression test: simulate the on-disk code changing after
    startup and confirm the watchdog notices and shuts the server down —
    without anyone needing to kill the process by hand."""
    import daemon

    monkeypatch.setattr(daemon, "SCRIPT_DIR", str(tmp_path))
    (tmp_path / "daemon.py").write_text("x = 1\n")
    monkeypatch.setattr(daemon, "_CODE_FINGERPRINT", daemon._compute_code_fingerprint())

    # Now change the code, as a plugin update / cache refresh would.
    new_time = os.path.getmtime(tmp_path / "daemon.py") + 5
    (tmp_path / "daemon.py").write_text("x = 2\n")
    os.utime(tmp_path / "daemon.py", (new_time, new_time))

    sleep_calls = []
    monkeypatch.setattr(daemon.time, "sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setattr(daemon, "_cleanup_state_files", lambda: sleep_calls.append("cleanup"))

    shutdown_called = []

    class _FakeServer:
        def shutdown(self):
            shutdown_called.append(True)

    # _watchdog spawns server.shutdown() on a background thread and then
    # returns — run it directly (not in a thread) since time.sleep is
    # mocked to return instantly, so the loop body executes synchronously.
    daemon._watchdog(_FakeServer())

    assert sleep_calls[0] == daemon.CODE_CHECK_INTERVAL_SECONDS
    assert "cleanup" in sleep_calls
    # shutdown() is dispatched on its own thread inside _watchdog; give it
    # a moment to actually run.
    import time as _time

    for _ in range(50):
        if shutdown_called:
            break
        _time.sleep(0.01)
    assert shutdown_called, "watchdog did not call server.shutdown() after detecting stale code"


def test_watchdog_does_not_shut_down_when_code_is_unchanged_and_active(monkeypatch, tmp_path):
    import daemon

    monkeypatch.setattr(daemon, "SCRIPT_DIR", str(tmp_path))
    (tmp_path / "daemon.py").write_text("x = 1\n")
    monkeypatch.setattr(daemon, "_CODE_FINGERPRINT", daemon._compute_code_fingerprint())
    monkeypatch.setattr(daemon, "_last_request_at", __import__("time").time())

    call_count = {"n": 0}

    def fake_sleep(_seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise KeyboardInterrupt  # stop the infinite loop for the test

    monkeypatch.setattr(daemon.time, "sleep", fake_sleep)

    class _FakeServer:
        def shutdown(self):
            raise AssertionError("shutdown() should not be called when code is unchanged and daemon is active")

    try:
        daemon._watchdog(_FakeServer())
    except KeyboardInterrupt:
        pass  # expected — proves the loop kept running instead of shutting down
