"""Resolve mem0 project_id and branch.

Resolution priority (project_id):
  1. MEM0_PROJECT_ID env var (explicit override)
  2. ~/.mem0/project_map.json lookup by cwd
  2b. ~/.mem0/project_map.json lookup by remote hash (self-healing fallback)
  3. Git repo root basename, e.g. /home/u/code/mem0 -> mem0. Matches
     claude-mem's getProjectName(): just the repo directory name, not an
     owner/org-qualified slug — a git remote pointing at a personal fork
     (owner == the mem0 user_id) would otherwise make the project_id look
     like it's prefixed with the user's identity, which it isn't. Resolving
     from the repo root (not the raw cwd) also keeps the id stable across
     subdirectories and worktrees, same as claude-mem.
  4. Fallback: basename of cwd (not a git repo, or git unavailable)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess


def resolve_project_id(cwd: str | None = None) -> str:
    if cwd is None:
        cwd = os.getcwd()

    # 1. Explicit override
    explicit = os.environ.get("MEM0_PROJECT_ID", "").strip()
    if explicit:
        return explicit

    # 2. project_map.json lookup
    map_path = os.path.expanduser("~/.mem0/project_map.json")
    if os.path.isfile(map_path):
        try:
            with open(map_path) as f:
                project_map = json.load(f)
            mapped = project_map.get(cwd, "").strip()
            if mapped:
                return mapped
            # 2b. Remote hash fallback (self-healing when folder is moved/renamed)
            remote_key = _remote_hash_key(cwd)
            if remote_key:
                mapped = project_map.get(remote_key, "").strip()
                if mapped:
                    # Self-heal: write the new CWD key so future lookups are fast
                    project_map[cwd] = mapped
                    try:
                        with open(map_path, "w") as f:
                            json.dump(project_map, f, indent=2)
                    except OSError:
                        pass
                    return mapped
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    # 3. Git repo root basename (falls through to 4 when not in a git repo)
    root = _git_repo_root(cwd)

    # 4. Fallback: basename of cwd
    return os.path.basename(os.path.normpath(root or cwd)) or "unknown"


def _git_repo_root(cwd: str) -> str:
    """Return the absolute repo-root path for *cwd*, or "" when not in a git
    repo (or git is unavailable). ``--show-toplevel`` resolves to the
    working-tree root even when invoked from a worktree or a nested
    subdirectory, so the caller's project name stays stable across both."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def resolve_branch(cwd: str | None = None) -> str:
    if cwd is None:
        cwd = os.getcwd()
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        branch = result.stdout.strip()
        return branch if branch else "unknown"
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def save_project_mapping(cwd: str, project_id: str) -> None:
    """Write cwd -> project_id (and remote hash key -> project_id) into ~/.mem0/project_map.json."""
    mem0_dir = os.path.expanduser("~/.mem0")
    os.makedirs(mem0_dir, exist_ok=True)
    map_path = os.path.join(mem0_dir, "project_map.json")
    project_map: dict[str, str] = {}
    if os.path.isfile(map_path):
        try:
            with open(map_path) as f:
                project_map = json.load(f)
        except (OSError, json.JSONDecodeError):
            project_map = {}
    project_map[cwd] = project_id
    # Also write the remote hash key so the mapping survives folder moves/renames
    remote_key = _remote_hash_key(cwd)
    if remote_key:
        project_map[remote_key] = project_id
    with open(map_path, "w") as f:
        json.dump(project_map, f, indent=2)


def _remote_hash_key(cwd: str | None = None) -> str:
    """Return a stable key derived from the git remote URL.

    Runs ``git config --get remote.origin.url`` in *cwd* and returns a string
    of the form ``remote:<sha256(url)[:16]>``.  Returns an empty string when
    the directory is not a git repo or has no remote configured.
    """
    if cwd is None:
        cwd = os.getcwd()
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        url = result.stdout.strip()
        if not url:
            return ""
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        return f"remote:{digest}"
    except (subprocess.CalledProcessError, OSError):
        return ""
