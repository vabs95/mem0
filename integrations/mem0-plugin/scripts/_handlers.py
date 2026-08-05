"""Shared hook-event handlers for the Mem0 plugin.

One implementation per lifecycle event (block_write, enforce_metadata,
on_file_read, session_start, user_prompt, post_tool_use, stop,
on_bash_output, pre_compact), used identically by every platform and OS
this plugin supports (Claude Code and Codex, on Windows/macOS/Linux).
``adapter_claude.py``/``adapter_codex.py`` are thin CLI entrypoints that
just read stdin JSON and call ``dispatch()`` here — they contain no
business logic of their own, so there is exactly one implementation of
each hook to maintain, not one per platform.

The only OS-specific code anywhere in this module is routed through
``_platform.spawn_bg`` — see that module's docstring for why.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# For spawn_bg() calls whose silent failure would be hard to notice
# (auto-import, one-shot setup) — unlike the MEM0_DEBUG-gated hooks.log
# above, this is always written regardless of MEM0_DEBUG, since it's not
# request/response tracing, just "did this background task blow up."
BACKGROUND_LOG_FILE = os.path.expanduser("~/.mem0/background.log")

from _api import api_mode, list_memories  # noqa: E402
from _identity import resolve_api_key, resolve_user_id  # noqa: E402
from _platform import spawn_bg  # noqa: E402
from _project import resolve_branch, resolve_project_id  # noqa: E402
from _search import format_results_for_context, search_memories, should_rerank  # noqa: E402


def _dedupe_by_id(*result_lists: list[dict]) -> list[dict]:
    seen: set[str] = set()
    combined: list[dict] = []
    for results in result_lists:
        for m in results:
            mid = m.get("id", "")
            if mid not in seen:
                seen.add(mid)
                combined.append(m)
    return combined

if os.environ.get("MEM0_DEBUG"):
    _log_dir = os.path.expanduser("~/.mem0")
    try:
        os.makedirs(_log_dir, exist_ok=True)
        sys.stderr = open(os.path.join(_log_dir, "hooks.log"), "a", encoding="utf-8")
    except OSError:
        pass


def cmd_block_write(input_data: dict) -> None:
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not file_path:
        sys.exit(0)
    normalized_path = file_path.replace("\\", "/")
    if "/.claude/" in normalized_path and ("/MEMORY.md" in normalized_path or "/memory/" in normalized_path):
        print(f"BLOCKED: Do not write to {file_path}. Use the mem0 MCP `add_memory` tool instead to persist memories. This project uses mem0 for all memory storage.", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def cmd_enforce_metadata(input_data: dict) -> None:
    tool_name = input_data.get("tool_name", "")
    handler = ""
    if tool_name in ("mcp__mem0__add_memory", "mcp__plugin_mem0_mem0__add_memory"):
        handler = "add_memory"
    elif tool_name in ("mcp__mem0__search_memories", "mcp__plugin_mem0_mem0__search_memories"):
        handler = "search_memories"
    elif tool_name in ("mcp__mem0__get_memories", "mcp__plugin_mem0_mem0__get_memories"):
        handler = "get_memories"
    elif tool_name in ("mcp__mem0__delete_all_memories", "mcp__plugin_mem0_mem0__delete_all_memories"):
        handler = "delete_all"
    else:
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    uid = resolve_user_id()
    aid = resolve_project_id(input_data.get("cwd"))
    agent_id = os.environ.get("MEM0_RESOLVED_AGENT_ID", "")
    global_search = os.environ.get("MEM0_GLOBAL_SEARCH", "false") == "true"
    changed = False

    def inject_top_level_identity(inp, u, a=None, ag_id=None):
        # user_id is always normalized to the resolved identity, never
        # merely filled when absent — a value the model supplied itself
        # may be stale or carried over from a different call's context
        # (see the project-scope drift found in testing: search reused a
        # value from the model's own reasoning instead of the identity
        # actually in effect). app_id/agent_id stay fill-gap-only since
        # cross-project association is a legitimate thing to want.
        #
        # Deliberately top-level fields only, never `filters` — the
        # bridge merges any `filters` the model supplies via a flat
        # dict.update() on top of the top-level user_id/agent_id/
        # run_id/project it already resolves from these same named
        # params (see server/mcp/mem0_mcp_bridge/client.py build_filters).
        # An AND-list injected into `filters` doesn't merge with that;
        # it collides, producing a self-contradictory/malformed filter
        # (e.g. two different user_id clauses ANDed together, which can
        # never match) — this was the actual cause of the empty-result
        # and 400 bugs found in testing, not a data problem.
        #
        ch = False
        if u and inp.get("user_id") != u:
            inp["user_id"] = u
            ch = True
        if a and not inp.get("app_id"):
            inp["app_id"] = a
            ch = True
        if ag_id and not inp.get("agent_id"):
            inp["agent_id"] = ag_id
            ch = True
        return ch

    inp = dict(tool_input)
    if handler == "add_memory":
        changed = inject_top_level_identity(inp, uid, aid, agent_id)
        meta = inp.get("metadata") or {}
        if "confidence" not in meta:
            meta["confidence"] = 0.7
            changed = True
        if "files" not in meta:
            meta["files"] = ["*"]
            changed = True
        if "source" not in meta:
            meta["source"] = "auto_capture"
            changed = True
        if "type" not in meta:
            meta["type"] = "task_learning"
            changed = True
        if meta.get("confidence", 0) >= 1.0 and "infer" not in inp:
            inp["infer"] = False
            changed = True
        if "session_id" not in meta:
            sid = os.environ.get("MEM0_SESSION_ID", "")
            if not sid:
                # Scoped by project too, not just user -- otherwise concurrent
                # sessions in different projects for the same user clobber
                # each other's cached session id.
                session_file = os.path.join(tempfile.gettempdir(), f"mem0_session_id_{uid}_{aid}")
                if os.path.isfile(session_file):
                    try:
                        with open(session_file, "r") as f:
                            sid = f.read().strip()
                    except OSError:
                        pass
            if sid:
                meta["session_id"] = sid
                changed = True
        if changed:
            inp["metadata"] = meta
    elif handler == "search_memories":
        if global_search:
            inp.pop("user_id", None)
            changed = True
        else:
            changed = inject_top_level_identity(inp, uid, aid)
    elif handler == "get_memories":
        if global_search:
            inp.pop("user_id", None)
            changed = True
        else:
            changed = inject_top_level_identity(inp, uid, aid)
    elif handler == "delete_all":
        changed = inject_top_level_identity(inp, uid, aid, agent_id)

    if changed:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": inp
            }
        }
        print(json.dumps(output))

    if handler == "add_memory":
        cat = tool_input.get("metadata", {}).get("type") or tool_input.get("metadata", {}).get("category") or ""
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "add", cat], cwd=input_data.get("cwd"))
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=add_memory"])
    elif handler in ("search_memories", "get_memories"):
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "search"], cwd=input_data.get("cwd"))
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=search_memories"])


def cmd_on_file_read(input_data: dict) -> None:
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        sys.exit(0)
    api_key = resolve_api_key()
    if not api_key:
        sys.exit(0)
    cwd = input_data.get("cwd") or "."

    try:
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "file_context.py"), file_path, cwd],
            capture_output=True,
            text=True
        )
        timeline = result.stdout.strip()
    except Exception:
        timeline = ""

    if timeline:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": timeline,
                "permissionDecision": "allow"
            }
        }
        print(json.dumps(output))
    sys.exit(0)


def cmd_session_start(input_data: dict) -> None:
    source = input_data.get("source", "startup")
    user = resolve_user_id()
    cwd = input_data.get("cwd") or "."
    project_id = resolve_project_id(cwd)
    # user+project scoping throughout this function: two concurrent sessions
    # for the same user in different projects must not share (and clobber)
    # each other's session id / dedup / counter files.
    scope = f"{user}_{project_id}"

    session_id = input_data.get("session_id") or ""
    if not session_id:
        session_id = f"ses_{int(time.time())}_{os.getpid()}"

    session_file = os.path.join(tempfile.gettempdir(), f"mem0_session_id_{scope}")
    try:
        with open(session_file, "w") as f:
            f.write(session_id)
    except OSError:
        pass

    if source == "startup":
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "init"], cwd=cwd)
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "load_settings.py"), "init"])

        for f in glob.glob(os.path.join(tempfile.gettempdir(), f"mem0_recent_reads_{scope}_*")):
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            os.remove(os.path.join(tempfile.gettempdir(), f"mem0_msg_count_{scope}"))
        except OSError:
            pass
        # Rubric flags are already keyed by session_id, which is unique per
        # session -- no need to (and no longer safe to) bulk-delete every
        # mem0_rubric_* file on every startup, which used to wipe other
        # concurrent sessions' already-shown flags too.

    api_key = resolve_api_key()
    branch = resolve_branch(cwd)
    global_search = os.environ.get("MEM0_GLOBAL_SEARCH", "false") == "true"

    mem_count = "?"
    if api_key:
        try:
            filters = {'OR': [{'user_id': '*'}]} if global_search else {'AND': [{'user_id': user}, {'app_id': project_id}]}
            # Cloud's paginated endpoint returns a real total `count`
            # independent of page_size, so page_size=1 is enough there.
            # Self-hosted's GET /memories has no such pagination metadata --
            # page_size just caps top_k, so len(results) IS the count,
            # silently capped at whatever page_size was requested. Request a
            # real sample size for self-hosted so this banner shows an
            # accurate count instead of always reporting at most 1.
            count_page_size = 1000 if api_mode() == "self_hosted" else 1
            status, data = list_memories(api_key, {'filters': filters, 'page_size': count_page_size}, timeout=5)
            if status in (200, 201):
                if isinstance(data, dict) and 'count' in data:
                    mem_count = str(data['count'])
                elif isinstance(data, dict) and 'results' in data:
                    mem_count = str(len(data['results']))
                    if count_page_size > 1 and len(data['results']) >= count_page_size:
                        mem_count += "+"
                elif isinstance(data, list):
                    mem_count = str(len(data))
                else:
                    mem_count = "0"
        except Exception:
            pass

    scope_label = "scope=global" if global_search else f"project={project_id}"
    scope_instr = (
        "Global search is ON — searches return all memories across all users and projects. Writes still use user_id: `%s`, app_id: `%s`." % (user, project_id)
        if global_search else
        "Always include `user_id` + `app_id` in every `search_memories` filter and `add_memory` call:\n- user_id: `%s`\n- app_id: `%s` (project scope — passed as top-level `app_id`, NOT in metadata)" % (user, project_id)
    )

    banner = f"""## Mem0 Active

`user={user} | {scope_label} | branch={branch} | memories={mem_count}`

IMPORTANT: In your FIRST response, display this exact status line as your opening line:

```
Mem0 Active | user={user} | {scope_label} | branch={branch} | memories={mem_count}
```

{scope_instr}

After completing any task, decision, or meaningful exchange, proactively store learnings via `add_memory`. Do NOT wait until the session ends — store memories incrementally as work progresses. Focus on: decisions made, bugs fixed, patterns discovered, user preferences, or task outcomes. Aim for 1–3 memories per substantial interaction.
"""
    print(banner)

    if source == "startup":
        if mem_count == "0":
            print("New project with 0 memories.")
        else:
            print("Search mem0 for recent decisions and task learnings before responding. Run 2 parallel searches: one for decision type, one for task_learning type.")
            try:
                env = os.environ.copy()
                env["MEM0_CWD"] = cwd
                res = subprocess.run(
                    [sys.executable, os.path.join(SCRIPT_DIR, "session_timeline.py")],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                timeline = res.stdout.strip()
                if timeline:
                    print("\n" + timeline)
            except Exception:
                pass

        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "auto_import.py")], log_path=BACKGROUND_LOG_FILE, cwd=cwd)
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "auto_setup_categories.py")], log_path=BACKGROUND_LOG_FILE, cwd=cwd)

    elif source == "resume":
        print("Session resumed. Search mem0 for session_state and decision memories to pick up where you left off. Run 2 parallel searches.")
    elif source == "compact":
        print("Context compacted. Search mem0 for session_state and decision memories to recover context. Run 2 parallel searches.")
        if os.environ.get("MEM0_AUTO_SAVE", "true") != "false":
            try:
                p = subprocess.Popen(
                    [sys.executable, os.path.join(SCRIPT_DIR, "capture_compact_summary.py")],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                p.communicate(input=json.dumps(input_data).encode('utf-8'))
            except Exception:
                pass

    spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "session_start", f"--source={source}", f"--memory_count={mem_count}"])


def cmd_user_prompt(input_data: dict) -> None:
    prompt = input_data.get("prompt") or ""
    if len(prompt) < 20:
        sys.exit(0)

    user = resolve_user_id()
    api_key = resolve_api_key()
    cwd = input_data.get("cwd") or "."
    project_id = resolve_project_id(cwd)
    session_id = input_data.get("session_id") or ""
    scope = f"{user}_{project_id}"

    if not session_id:
        session_file = os.path.join(tempfile.gettempdir(), f"mem0_session_id_{scope}")
        if os.path.isfile(session_file):
            try:
                with open(session_file, "r") as f:
                    session_id = f.read().strip()
            except OSError:
                pass
    if not session_id:
        session_id = f"default_{user}"

    rubric_dir = os.environ.get("MEM0_RUBRIC_DIR") or tempfile.gettempdir()
    # session_id comes from hook stdin JSON -- sanitize before using it in a
    # filesystem path in case a future caller ever feeds it something other
    # than the harness's own session id.
    safe_session_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id)
    rubric_flag = os.path.join(rubric_dir, f"mem0_rubric_{safe_session_id}")
    rubric_already_shown = os.path.isfile(rubric_flag)

    msg_count_file = os.path.join(tempfile.gettempdir(), f"mem0_msg_count_{scope}")
    msg_count = 0
    if os.path.isfile(msg_count_file):
        try:
            with open(msg_count_file, "r") as f:
                msg_count = int(f.read().strip() or "0")
        except (OSError, ValueError):
            pass
    msg_count += 1
    try:
        with open(msg_count_file, "w") as f:
            f.write(str(msg_count))
    except OSError:
        pass

    has_error = False
    if re.search(r'(Traceback|panic:)', prompt):
        has_error = True
    elif re.search(r'^\s*fatal: ', prompt, re.MULTILINE):
        has_error = True
    elif len(re.findall(r'(Error:|Exception:|FAIL:)', prompt)) >= 2:
        has_error = True

    file_paths = re.findall(r'([a-zA-Z0-9_./-]+\.(?:py|ts|tsx|js|jsx|rs|go|rb|java|sh|yaml|yml|json|toml|md|sql|css|html))\b', prompt)
    file_paths = file_paths[:5]

    has_resume = False
    if re.search(r'(where (did )?(we|I) (leave|left) off|continue (from )?(where|last)|what were we (working|doing)|pick up where|resume (from |where)|what.s the (current|latest) (state|status)|catch me up|where are we)', prompt, re.IGNORECASE):
        has_resume = True

    has_remember = False
    if re.search(r'(remember (this|that)|save (this|that) (fact|info|memory|note)|store (this|that)|don.t forget (this|that)|keep (this|that) in (mind|memory))', prompt, re.IGNORECASE):
        has_remember = True

    telem_args = [sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "user_prompt"]
    if has_error:
        telem_args.append("--error_detected")
    if file_paths:
        telem_args.append("--file_paths_detected")
    if has_resume:
        telem_args.append("--resume_detected")
    if has_remember:
        telem_args.append("--remember_detected")
    spawn_bg(telem_args)

    if not api_key:
        ctx_parts = []
        if has_error:
            ctx_parts.append("Error detected in prompt. Set MEM0_API_KEY to search past debugging context.")
        if file_paths:
            ctx_parts.append(f"File paths detected: {', '.join(file_paths)}")
        if ctx_parts:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": "\n".join(ctx_parts)
                }
            }
            print(json.dumps(output))
        sys.exit(0)

    ctx_parts = []

    if has_resume:
        rerank = should_rerank()
        state = search_memories(
            api_key, user, project_id, "session state current task", metadata_type="session_state", top_k=3, rerank=rerank
        )
        decisions = search_memories(
            api_key, user, project_id, "recent decisions and learnings", metadata_type="decision", top_k=3, rerank=rerank
        )
        unique = _dedupe_by_id(state, decisions)
        if unique:
            ctx_parts.append(
                format_results_for_context(unique, heading="Session context recovered from mem0")
                + "\nThese memories provide context for resuming work."
            )
        else:
            ctx_parts.append("No session state found in mem0.")

    if not has_resume and os.environ.get("MEM0_PREFETCH", "true") != "false":
        results = search_memories(api_key, user, project_id, prompt, top_k=5, rerank=should_rerank())
        if results:
            ctx_parts.append(format_results_for_context(results, heading="Relevant memories (auto-retrieved for this request)"))

    if has_remember:
        ctx_parts.append("Remember intent detected. The /mem0:remember skill auto-classifies, sets confidence=1.0, and stores verbatim.")

    if not rubric_already_shown:
        ctx_parts.append("Mem0 searches apply when user references past work, decision questions, errors, or non-trivial tasks. Queries use noun-phrases, 2-4 parallel calls with different `type` filters (flat key, e.g. filters={\"type\": \"decision\"} -- NOT nested as {\"metadata\": {\"type\": ...}}, which the self-hosted backend rejects with a 400), and include user_id + app_id. For multi-part or comparative questions, run follow-up searches and combine results before answering -- one search is rarely enough.")
        try:
            with open(rubric_flag, "w") as f:
                f.write("injected")
        except OSError:
            pass

    if has_error:
        ctx_parts.append("Error detected in prompt. Prior occurrences are available in mem0 via anti_pattern and task_learning type filters.")
    if file_paths:
        ctx_parts.append(f"File paths detected: {', '.join(file_paths)}")

    transcript_path = input_data.get("transcript_path") or ""
    if os.environ.get("MEM0_AUTO_SAVE", "true") != "false" and (msg_count % 3) == 0 and msg_count > 0 and transcript_path:
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "auto_capture.py"), transcript_path], log_path=BACKGROUND_LOG_FILE, cwd=cwd)

    adds = 0
    stats_file = os.path.join(tempfile.gettempdir(), f"mem0_session_stats_{scope}.json")
    if os.path.isfile(stats_file):
        try:
            with open(stats_file, "r") as f:
                stats = json.load(f)
                adds = stats.get("adds", 0)
        except Exception:
            pass
    if msg_count >= 3 and adds < (msg_count // 3):
        ctx_parts.append("After responding, store any new decisions, learnings, or preferences from this exchange via add_memory. Pass metadata with category ('decision', 'bug_fix', 'architecture', 'user_preference', 'task_learning') and importance rating (1-10 scale). Keep it to 1 sentence per memory.")

    if ctx_parts:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n\n".join(ctx_parts)
            }
        }
        print(json.dumps(output))
    sys.exit(0)


def cmd_post_tool_use(input_data: dict) -> None:
    tool_name = input_data.get("tool_name", "")
    cwd = input_data.get("cwd")
    if tool_name.endswith("__add_memory"):
        tool_input = input_data.get("tool_input", {})
        cat = tool_input.get("metadata", {}).get("type") or tool_input.get("metadata", {}).get("category") or ""
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "add", cat], cwd=cwd)
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=add_memory"])
    elif tool_name.endswith("__search_memories") or tool_name.endswith("__get_memories"):
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "search"], cwd=cwd)
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=search_memories"])
    elif tool_name.endswith("__delete_memory"):
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=delete_memory"])
    elif tool_name.endswith("__update_memory"):
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=update_memory"])
    sys.exit(0)


def cmd_stop(input_data: dict) -> None:
    if input_data.get("agent_id"):
        sys.exit(0)
    api_key = resolve_api_key()
    if not api_key:
        sys.exit(0)
    if os.environ.get("MEM0_AUTO_SAVE", "true") == "false":
        sys.exit(0)
    transcript_path = input_data.get("transcript_path") or ""
    if not transcript_path:
        sys.exit(0)

    try:
        with open(BACKGROUND_LOG_FILE, "a") as _log_file:
            p = subprocess.Popen(
                [sys.executable, os.path.join(SCRIPT_DIR, "capture_session_summary.py")],
                stdin=subprocess.PIPE,
                stdout=_log_file,
                stderr=_log_file,
            )
            p.communicate(input=json.dumps(input_data).encode('utf-8'))
    except Exception:
        pass

    spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "session_stop"])
    sys.exit(0)


def cmd_on_bash_output(input_data: dict) -> None:
    tool_response = input_data.get("tool_response") or ""
    if len(tool_response) < 50:
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command") or ""
    if any(git_cmd in command for git_cmd in ("git commit", "git merge", "git rebase")):
        sys.exit(0)

    has_error = False
    if re.search(r'(Traceback \(most recent call last\)|panic: |FATAL:|error\[E[0-9]+\])', tool_response):
        has_error = True
    elif len(re.findall(r'(Error:|Exception:)', tool_response)) >= 2:
        has_error = True

    if not has_error:
        sys.exit(0)

    error_line = ""
    for line in tool_response.splitlines():
        if re.search(r'(Error:|Exception:|panic:|FAIL:|fatal:)', line, re.IGNORECASE):
            error_line = line.strip()[:120]
            break

    trace_files = sorted(list(set(re.findall(r'([a-zA-Z0-9_./-]+\.(?:py|ts|tsx|js|jsx|rs|go|rb|java|sh))(:[0-9]+)?', tool_response))))
    trace_files = [tf[0] + (tf[1] if tf[1] else "") for tf in trace_files][:5]

    file_display = ""
    if trace_files:
        file_display = "\n".join(f"  - {tf}" for tf in trace_files)

    user = resolve_user_id()
    error_query = error_line[:80]

    spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "bash_error", "--error_detected"])

    api_key = resolve_api_key()
    if not api_key:
        sys.exit(0)

    cwd = input_data.get("cwd") or "."
    project_id = resolve_project_id(cwd)

    rerank = should_rerank()
    anti_patterns = search_memories(api_key, user, project_id, error_query, metadata_type="anti_pattern", top_k=3, rerank=rerank)
    bug_fixes = search_memories(api_key, user, project_id, error_query, metadata_type="bug_fix", top_k=3, rerank=rerank)
    results = format_results_for_context(_dedupe_by_id(anti_patterns, bug_fixes), heading="Prior error memories")

    ctx = f"Error detected in command output\n\n`{command}` produced an error:\n> {error_line}\n"
    if file_display:
        ctx += f"\nFiles in stack trace:\n{file_display}\n"
    if results:
        ctx += f"\n{results}\n"
    ctx += "\nResolved errors are stored as anti_pattern or bug_fix memories for future reference."

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": ctx
        }
    }
    print(json.dumps(output))
    sys.exit(0)


def cmd_pre_compact(input_data: dict) -> None:
    spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "pre_compact"])
    try:
        p = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "on_pre_compact.py"), "--source=pre-compaction"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        p.communicate(input=json.dumps(input_data).encode('utf-8'))
    except Exception:
        pass
    sys.exit(0)


_DISPATCH = {
    "block_write": cmd_block_write,
    "enforce_metadata": cmd_enforce_metadata,
    "on_file_read": cmd_on_file_read,
    "session_start": cmd_session_start,
    "user_prompt": cmd_user_prompt,
    "post_tool_use": cmd_post_tool_use,
    "stop": cmd_stop,
    "on_bash_output": cmd_on_bash_output,
    "pre_compact": cmd_pre_compact,
}


def dispatch(hook_name: str, input_data: dict) -> None:
    handler = _DISPATCH.get(hook_name)
    if handler is None:
        print(f"Unknown hook name: {hook_name}", file=sys.stderr)
        sys.exit(1)
    handler(input_data)


DAEMON_PORT_FILE = os.path.expanduser("~/.mem0/daemon.port")
DAEMON_LOG_FILE = os.path.expanduser("~/.mem0/daemon.log")
_DAEMON_CONNECT_TIMEOUT = 0.05
_DAEMON_SPAWN_RETRY_TOTAL = 0.5
# Hook handlers can make a real network call (e.g. session_start fetching
# context from a remote self-hosted mem0 API over Tailscale), so the actual
# dispatch request needs real headroom — unlike _DAEMON_CONNECT_TIMEOUT,
# which only probes whether the daemon's socket is accepting connections yet.
_DAEMON_REQUEST_TIMEOUT = 20.0

# Forwarded to the daemon on every dispatch so its identity resolution
# reflects *this* invocation's environment rather than whatever was set
# when the long-lived daemon process was originally spawned — see
# daemon.py's _apply_request_env for the receiving side. MEM0_PLATFORM is
# included so timeline events are attributed to the calling editor/CLI
# (e.g. "codex") rather than whichever platform's hook happened to spawn
# the daemon first.
_IDENTITY_ENV_KEYS = ("MEM0_USER_ID", "MEM0_PROJECT_ID", "MEM0_API_KEY", "MEM0_AGENT_ID", "MEM0_PLATFORM")


def _read_daemon_port() -> int | None:
    try:
        with open(DAEMON_PORT_FILE, "r") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _call_daemon(port: int, hook_name: str, input_data: dict, timeout: float) -> dict | None:
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        body = json.dumps(input_data).encode("utf-8")
        conn.request("POST", f"/hook/{hook_name}", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        return data
    except Exception:
        return None
    finally:
        conn.close()


def _daemon_is_up(port: int, timeout: float) -> bool:
    """Cheap readiness probe — GET /health only, never the real hook
    endpoint. Used for the spawn-retry loop below so that loop can poll
    quickly without each attempt being a genuine hook dispatch."""
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/health")
        return conn.getresponse().status == 200
    except Exception:
        return False
    finally:
        conn.close()


def _exit_with_daemon_result(result: dict) -> None:
    sys.stdout.write(result.get("stdout", ""))
    sys.exit(result.get("exit_code", 0))


def _dispatch_via_daemon(hook_name: str, input_data: dict) -> None:
    """Try the warm daemon; spawn it if absent. Returns normally (does not
    exit) only if the daemon never became reachable — the caller then
    falls back to plain in-process dispatch. That fallback is the
    crash-safety net: if the daemon never comes up, hooks behave exactly
    as they did before it existed, just without the warm-cache speedup.

    Sends the real hook POST at most once per daemon-discovery path (an
    already-running daemon, or one freshly spawned here). Earlier this
    retried the actual POST itself on every short poll-interval timeout —
    against an already-running-but-slow daemon (e.g. session_start doing a
    real network call to a remote mem0 API) each retry was a genuine
    re-dispatch, not just a reconnect, so a single slow hook call could
    fire the handler — and post a timeline event — several times over.
    Polling now uses a separate, cheap /health probe instead."""
    env = {k: os.environ[k] for k in _IDENTITY_ENV_KEYS if os.environ.get(k)}
    payload = {**input_data, "_env": env}

    port = _read_daemon_port()
    if port is not None and _daemon_is_up(port, _DAEMON_CONNECT_TIMEOUT):
        result = _call_daemon(port, hook_name, payload, timeout=_DAEMON_REQUEST_TIMEOUT)
        if result is not None:
            _exit_with_daemon_result(result)
        return

    from _platform import spawn_daemon_detached

    spawn_daemon_detached([sys.executable, os.path.join(SCRIPT_DIR, "daemon.py")], DAEMON_LOG_FILE)

    deadline = time.time() + _DAEMON_SPAWN_RETRY_TOTAL
    port = None
    while time.time() < deadline:
        candidate = _read_daemon_port()
        if candidate is not None and _daemon_is_up(candidate, _DAEMON_CONNECT_TIMEOUT):
            port = candidate
            break
        time.sleep(0.05)

    if port is not None:
        result = _call_daemon(port, hook_name, payload, timeout=_DAEMON_REQUEST_TIMEOUT)
        if result is not None:
            _exit_with_daemon_result(result)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python _handlers.py <hook_name>", file=sys.stderr)
        sys.exit(1)

    hook_name = sys.argv[1]
    input_data: dict = {}
    try:
        input_data = json.loads(sys.stdin.read())
    except Exception:
        pass

    if os.environ.get("MEM0_NO_DAEMON") != "true":
        _dispatch_via_daemon(hook_name, input_data)  # exits directly on success

    dispatch(hook_name, input_data)


if __name__ == "__main__":
    main()
