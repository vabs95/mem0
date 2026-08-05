"""Tests for rubric deduplication in _handlers.py's cmd_user_prompt.

Runs _handlers.py as a subprocess (not an in-process import) so this stays a
true characterization test across the Claude Code / Codex hook boundary —
the same invocation shape hooks.json and codex-hooks.json actually use.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")


@pytest.fixture(autouse=True)
def _clean_rubric_flag(tmp_path, monkeypatch):
    """Use a temp dir for the rubric flag file and clean msg counter."""
    monkeypatch.setenv("MEM0_RUBRIC_DIR", str(tmp_path))
    msg_count_file = "/tmp/mem0_msg_count_testuser"
    yield
    if os.path.exists(msg_count_file):
        os.unlink(msg_count_file)


def _run_hook(prompt: str, env_overrides: dict | None = None, session_id: str = "test-sess-001") -> str:
    """Run `_handlers.py user_prompt` with a simulated prompt and return stdout."""
    env = {
        **os.environ,
        "USER": "testuser",
        "MEM0_API_KEY": "test-key-123",
        "MEM0_RESOLVED_USER_ID": "testuser",
        "MEM0_PROJECT_ID": "test-project",
        "MEM0_BRANCH": "main",
        "MEM0_PREFETCH": "false",
        "MEM0_NO_DAEMON": "true",
    }
    if env_overrides:
        env.update(env_overrides)

    input_json = json.dumps({"prompt": prompt, "session_id": session_id})
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "_handlers.py"), "user_prompt"],
        input=input_json,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return result.stdout


def test_first_prompt_gets_full_rubric():
    """First substantial prompt of session gets full memory check rubric.

    Guidance must say `type` as a flat filter key, not "metadata.type" —
    the latter reads naturally as {"metadata": {"type": ...}}, a nested
    shape the self-hosted backend rejects with a 400 (confirmed live: an
    agent following the old wording hit exactly this). See _handlers.py's
    rubric string.
    """
    output = _run_hook("How should we refactor the auth module?")
    assert "Mem0 searches apply" in output
    assert '`type` filters' in output
    assert "metadata.type" not in output


def test_second_prompt_gets_no_rubric():
    """Second prompt of session emits nothing — rubric and tips only on first prompt."""
    _run_hook("How should we refactor the auth module?")
    output = _run_hook("What about the database layer?")
    assert output.strip() == ""
