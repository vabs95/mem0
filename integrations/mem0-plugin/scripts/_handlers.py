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

from _api import add_memory, list_memories
from _identity import resolve_api_key, resolve_user_id
from _platform import spawn_bg
from _project import resolve_branch, resolve_project_id

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

    def inject_top_level_identity(inp, u, a, ag_id):
        ch = False
        if u and not inp.get("user_id"):
            inp["user_id"] = u
            ch = True
        if a and not inp.get("app_id"):
            inp["app_id"] = a
            ch = True
        if ag_id and not inp.get("agent_id"):
            inp["agent_id"] = ag_id
            ch = True
        return ch

    def inject_filter_identity(inp, u, a):
        if not u and not a:
            return False
        filters = inp.get("filters")
        if filters is None:
            and_clauses = []
            if u:
                and_clauses.append({"user_id": u})
            if a:
                and_clauses.append({"app_id": a})
            inp["filters"] = {"AND": and_clauses}
            return True
        if not isinstance(filters, dict):
            return False
        and_clauses = filters.get("AND")
        if and_clauses is None:
            has_uid = "user_id" in filters
            has_aid = "app_id" in filters
            if has_uid and has_aid:
                return False
            existing = []
            for k, v in list(filters.items()):
                existing.append({k: v})
            ch = False
            if u and not has_uid:
                existing.append({"user_id": u})
                ch = True
            if a and not has_aid:
                existing.append({"app_id": a})
                ch = True
            if ch:
                inp["filters"] = {"AND": existing}
            return ch
        if not isinstance(and_clauses, list):
            return False
        has_uid = any("user_id" in c for c in and_clauses if isinstance(c, dict))
        has_aid = any("app_id" in c for c in and_clauses if isinstance(c, dict))
        ch = False
        if u and not has_uid:
            and_clauses.append({"user_id": u})
            ch = True
        if a and not has_aid:
            and_clauses.append({"app_id": a})
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
                session_file = os.path.join(tempfile.gettempdir(), f"mem0_session_id_{uid}")
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
    elif handler in ("search_memories", "get_memories"):
        if global_search:
            inp["filters"] = {"OR": [{"user_id": "*"}]}
            changed = True
        else:
            changed = inject_filter_identity(inp, uid, aid)
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
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "add", cat])
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=add_memory"])
    elif handler in ("search_memories", "get_memories"):
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "search"])
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

    session_id = input_data.get("session_id") or ""
    if not session_id:
        session_id = f"ses_{int(time.time())}_{os.getpid()}"

    session_file = os.path.join(tempfile.gettempdir(), f"mem0_session_id_{user}")
    try:
        with open(session_file, "w") as f:
            f.write(session_id)
    except OSError:
        pass

    if source == "startup":
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "init"])
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "load_settings.py"), "init"])

        for f in glob.glob(os.path.join(tempfile.gettempdir(), f"mem0_recent_reads_{user}_*")):
            try:
                os.remove(f)
            except OSError:
                pass
        for filename in [f"mem0_rubric_injected_{user}", f"mem0_msg_count_{user}"]:
            try:
                os.remove(os.path.join(tempfile.gettempdir(), filename))
            except OSError:
                pass
        for f in glob.glob(os.path.join(tempfile.gettempdir(), "mem0_rubric_*")):
            try:
                os.remove(f)
            except OSError:
                pass

    api_key = resolve_api_key()
    cwd = input_data.get("cwd") or "."
    project_id = resolve_project_id(cwd)
    branch = resolve_branch(cwd)
    global_search = os.environ.get("MEM0_GLOBAL_SEARCH", "false") == "true"

    mem_count = "?"
    if api_key:
        try:
            filters = {'OR': [{'user_id': '*'}]} if global_search else {'AND': [{'user_id': user}, {'app_id': project_id}]}
            status, data = list_memories(api_key, {'filters': filters, 'page_size': 1}, timeout=5)
            if status in (200, 201):
                if isinstance(data, dict) and 'count' in data:
                    mem_count = str(data['count'])
                elif isinstance(data, dict) and 'results' in data:
                    mem_count = str(len(data['results']))
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

        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "auto_import.py")])
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "auto_setup_categories.py")])

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

    if not session_id:
        session_file = os.path.join(tempfile.gettempdir(), f"mem0_session_id_{user}")
        if os.path.isfile(session_file):
            try:
                with open(session_file, "r") as f:
                    session_id = f.read().strip()
            except OSError:
                pass
    if not session_id:
        session_id = f"default_{user}"

    rubric_dir = os.environ.get("MEM0_RUBRIC_DIR") or tempfile.gettempdir()
    rubric_flag = os.path.join(rubric_dir, f"mem0_rubric_{session_id}")
    rubric_already_shown = os.path.isfile(rubric_flag)

    msg_count_file = os.path.join(tempfile.gettempdir(), f"mem0_msg_count_{user}")
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
    if has_error: telem_args.append("--error_detected")
    if file_paths: telem_args.append("--file_paths_detected")
    if has_resume: telem_args.append("--resume_detected")
    if has_remember: telem_args.append("--remember_detected")
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
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = SCRIPT_DIR
            env["MEM0_SEARCH_USER"] = user
            env["MEM0_PROJECT_ID"] = project_id
            res = subprocess.run(
                [sys.executable, "-c", """
import os, sys
sys.path.insert(0, os.environ.get('PYTHONPATH', '.'))
from _search import search_memories, format_results_for_context, should_rerank
api_key = os.environ.get('MEM0_API_KEY', '')
user_id = os.environ.get('MEM0_SEARCH_USER', 'default')
project_id = os.environ.get('MEM0_PROJECT_ID', 'unknown')
rerank = should_rerank()
state = search_memories(api_key, user_id, project_id, 'session state current task', metadata_type='session_state', top_k=3, rerank=rerank)
decisions = search_memories(api_key, user_id, project_id, 'recent decisions and learnings', metadata_type='decision', top_k=3, rerank=rerank)
combined = state + decisions
seen = set()
unique = []
for m in combined:
    mid = m.get('id', '')
    if mid not in seen:
        seen.add(mid)
        unique.append(m)
if unique:
    print(format_results_for_context(unique, heading='Session context recovered from mem0'))
    print('\\nThese memories provide context for resuming work.')
else:
    print('No session state found in mem0.')
"""],
                env=env, capture_output=True, text=True
            )
            resume_results = res.stdout.strip()
            if resume_results:
                ctx_parts.append(resume_results)
        except Exception:
            pass

    if not has_resume and os.environ.get("MEM0_PREFETCH", "true") != "false":
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = SCRIPT_DIR
            env["MEM0_SEARCH_USER"] = user
            env["MEM0_PROJECT_ID"] = project_id
            env["MEM0_SEARCH_QUERY"] = prompt
            res = subprocess.run(
                [sys.executable, "-c", """
import os, sys
sys.path.insert(0, os.environ.get('PYTHONPATH', '.'))
from _search import search_memories, format_results_for_context, should_rerank
api_key = os.environ.get('MEM0_API_KEY', '')
user_id = os.environ.get('MEM0_SEARCH_USER', 'default')
project_id = os.environ.get('MEM0_PROJECT_ID', 'unknown')
query = os.environ.get('MEM0_SEARCH_QUERY', '')
results = search_memories(api_key, user_id, project_id, query, top_k=5, rerank=should_rerank())
if results:
    print(format_results_for_context(results, heading='Relevant memories (auto-retrieved for this request)'))
"""],
                env=env, capture_output=True, text=True
            )
            prefetch_results = res.stdout.strip()
            if prefetch_results:
                ctx_parts.append(prefetch_results)
        except Exception:
            pass

    if has_remember:
        ctx_parts.append("Remember intent detected. The /mem0:remember skill auto-classifies, sets confidence=1.0, and stores verbatim.")

    if not rubric_already_shown:
        ctx_parts.append("Mem0 searches apply when user references past work, decision questions, errors, or non-trivial tasks. Queries use noun-phrases, 2-4 parallel calls with different metadata.type filters, and include user_id + app_id. For multi-part or comparative questions, run follow-up searches and combine results before answering -- one search is rarely enough.")
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
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "auto_capture.py"), transcript_path])

    adds = 0
    stats_file = os.path.join(tempfile.gettempdir(), f"mem0_session_stats_{user}.json")
    if os.path.isfile(stats_file):
        try:
            with open(stats_file, "r") as f:
                stats = json.load(f)
                adds = stats.get("adds", 0)
        except Exception:
            pass
    if msg_count >= 3 and adds < (msg_count // 3):
        ctx_parts.append("After responding, store any new decisions, learnings, or preferences from this exchange via add_memory. Keep it to 1 sentence per memory.")

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
    if tool_name.endswith("__add_memory"):
        tool_input = input_data.get("tool_input", {})
        cat = tool_input.get("metadata", {}).get("type") or tool_input.get("metadata", {}).get("category") or ""
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "add", cat])
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "telemetry.py"), "tool_use", "--tool=add_memory"])
    elif tool_name.endswith("__search_memories") or tool_name.endswith("__get_memories"):
        spawn_bg([sys.executable, os.path.join(SCRIPT_DIR, "session_stats.py"), "search"])
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
        p = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "capture_session_summary.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
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

    results = ""
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPT_DIR
        env["MEM0_SEARCH_QUERY"] = error_query
        env["MEM0_SEARCH_USER"] = user
        env["MEM0_PROJECT_ID"] = project_id
        res = subprocess.run(
            [sys.executable, "-c", """
import os, sys
sys.path.insert(0, os.environ.get('PYTHONPATH', '.'))
from _search import search_memories, format_results_for_context, should_rerank
api_key = os.environ.get('MEM0_API_KEY', '')
user_id = os.environ.get('MEM0_SEARCH_USER', 'default')
project_id = os.environ.get('MEM0_PROJECT_ID', 'unknown')
query = os.environ.get('MEM0_SEARCH_QUERY', '')
rerank = should_rerank()
r1 = search_memories(api_key, user_id, project_id, query, metadata_type='anti_pattern', top_k=3, rerank=rerank)
r2 = search_memories(api_key, user_id, project_id, query, metadata_type='bug_fix', top_k=3, rerank=rerank)
seen = set()
combined = []
for m in r1 + r2:
    mid = m.get('id', '')
    if mid not in seen:
        seen.add(mid)
        combined.append(m)
print(format_results_for_context(combined, heading='Prior error memories'), end='')
"""],
            env=env, capture_output=True, text=True
        )
        results = res.stdout.strip()
    except Exception:
        pass

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


def _exit_with_daemon_result(result: dict) -> None:
    sys.stdout.write(result.get("stdout", ""))
    sys.exit(result.get("exit_code", 0))


def _dispatch_via_daemon(hook_name: str, input_data: dict) -> None:
    """Try the warm daemon; spawn it if absent. Returns normally (does not
    exit) only if the daemon never became reachable — the caller then
    falls back to plain in-process dispatch. That fallback is the
    crash-safety net: if the daemon never comes up, hooks behave exactly
    as they did before it existed, just without the warm-cache speedup."""
    port = _read_daemon_port()
    if port is not None:
        result = _call_daemon(port, hook_name, input_data, timeout=2.0)
        if result is not None:
            _exit_with_daemon_result(result)

    from _platform import spawn_daemon_detached

    spawn_daemon_detached([sys.executable, os.path.join(SCRIPT_DIR, "daemon.py")], DAEMON_LOG_FILE)

    deadline = time.time() + _DAEMON_SPAWN_RETRY_TOTAL
    while time.time() < deadline:
        port = _read_daemon_port()
        if port is not None:
            result = _call_daemon(port, hook_name, input_data, timeout=_DAEMON_CONNECT_TIMEOUT)
            if result is not None:
                _exit_with_daemon_result(result)
        time.sleep(0.05)


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
