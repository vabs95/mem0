"""Tests for daemon.py's timeline-event body building and its concurrency
safety across the identity-env-apply / handler-dispatch / body-build cycle.

Regression coverage for a real production bug: the daemon is a single
process shared by every editor on the machine (Claude Code, Codex, ...).
_apply_request_env used to run outside any lock, and the timeline event's
body used to be built by a detached background thread reading
os.environ/cached resolvers *after* _dispatch_lock was released — so a
concurrent request from a different platform could overwrite
MEM0_PLATFORM/MEM0_USER_ID/etc. in the window before the background thread
got scheduled, misattributing the event (observed live: Codex-originated
timeline events logged with source_agent "claude-code" because a Claude
Code hook fired around the same time). The fix moves env-apply +
dispatch + body-building into one atomic region under _dispatch_lock, so
the background thread only ever does pure network I/O on an
already-resolved dict.
"""

from __future__ import annotations

import threading
from collections import Counter


def _rig(monkeypatch):
    import daemon

    monkeypatch.setattr(daemon._handlers, "dispatch", lambda hook_name, input_data: None)
    monkeypatch.setattr(daemon._handlers, "resolve_api_key", lambda: "fake-key")
    monkeypatch.setattr(daemon._handlers, "resolve_user_id", lambda: "vabs")
    monkeypatch.setattr(daemon._handlers, "resolve_project_id", lambda cwd=None: "test-project")
    return daemon


def test_build_timeline_body_reclassifies_add_memory(monkeypatch):
    daemon = _rig(monkeypatch)
    input_data = {
        "tool_name": "mcp__mem0__add_memory",
        "tool_input": {"text": "user prefers dark mode", "metadata": {"type": "decision"}},
        "tool_response": '{"results": [{"id": "mem-1", "event": "ADD"}]}',
    }
    body = daemon._build_timeline_body("post_tool_use", input_data)
    assert body["event_type"] == "add_memory"
    assert body["category"] == "decision"
    assert body["memory_ids"] == ["mem-1"]
    assert body["summary"] == "user prefers dark mode"


def test_build_timeline_body_ignores_non_add_memory_tool_calls(monkeypatch):
    daemon = _rig(monkeypatch)
    input_data = {"tool_name": "mcp__mem0__search_memories", "tool_response": "..."}
    body = daemon._build_timeline_body("post_tool_use", input_data)
    assert body["event_type"] == "post_tool_use"
    assert body["category"] is None
    assert body["memory_ids"] == []


def test_build_timeline_body_returns_none_without_api_key(monkeypatch):
    daemon = _rig(monkeypatch)
    monkeypatch.setattr(daemon._handlers, "resolve_api_key", lambda: "")
    assert daemon._build_timeline_body("stop", {}) is None


def test_no_cross_platform_attribution_leakage_under_concurrency(monkeypatch):
    """The actual regression test: hammer _run_captured from several
    threads concurrently, each claiming a different MEM0_PLATFORM, and
    verify every produced timeline body has exactly the platform its own
    request claimed — never a neighbor's."""
    daemon = _rig(monkeypatch)

    captured: list[dict] = []
    capture_lock = threading.Lock()

    def fake_dispatch(hook_name, input_data):
        import time

        time.sleep(0.005)  # widen the race window a slow handler would leave

    def fake_send(body):
        with capture_lock:
            captured.append(body)

    monkeypatch.setattr(daemon._handlers, "dispatch", fake_dispatch)
    monkeypatch.setattr(daemon, "_send_timeline_event", fake_send)

    platforms = ["codex", "claude-code", "cursor"]
    per_platform = 20

    def worker(platform: str) -> None:
        for _ in range(per_platform):
            daemon._run_captured("stop", {}, {"MEM0_PLATFORM": platform})

    threads = [threading.Thread(target=worker, args=(p,)) for p in platforms]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(captured) == len(platforms) * per_platform
    counts = Counter(b["source_agent"] for b in captured)
    for platform in platforms:
        assert counts[platform] == per_platform, f"{platform}: expected {per_platform}, got {counts[platform]}"
