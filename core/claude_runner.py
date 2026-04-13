"""
Async Claude CLI subprocess wrapper.

Builds the correct `claude -p ...` command for a given profile,
manages session resumption, parses NOTIFY: sentinels from stdout.
"""

import asyncio
import glob
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

WORKSPACE = "/workspace"

# Tool restrictions per profile
PROFILE_TOOLS: dict[str, list[str] | None] = {
    "ceo":       ["Read", "WebSearch", "WebFetch"],
    "architect": ["Read", "Glob", "Grep", "Bash(git log:*)", "Bash(git diff:*)", "WebSearch"],
    "developer": None,  # all tools
    "reviewer":  ["Read", "Glob", "Grep", "Bash(gh:*)", "Bash(git:*)"],
}

# MCP config paths per profile (relative to WORKSPACE)
PROFILE_MCP: dict[str, str | None] = {
    "ceo":       None,
    "architect": None,
    "developer": "/workspace/mcp/developer.mcp.json",
    "reviewer":  "/workspace/mcp/reviewer.mcp.json",
}


@dataclass
class RunResult:
    text: str                          # Claude's response (sentinel lines stripped)
    session_id: str | None             # session ID used or created
    notifications: list[str] = field(default_factory=list)   # parsed NOTIFY: messages
    task_sentinels: list[dict] = field(default_factory=list)  # parsed TASK: directives
    artifact_sentinels: list[dict] = field(default_factory=list)  # parsed ARTIFACT: directives
    returncode: int = 0


def _get_project_dir() -> str:
    encoded = WORKSPACE.replace("/", "-")
    return str(Path.home() / ".claude" / "projects" / encoded)


def _snapshot_sessions() -> set[str]:
    pattern = os.path.join(_get_project_dir(), "*.jsonl")
    return {Path(f).stem for f in glob.glob(pattern)}


def _find_new_session(before: set[str]) -> str | None:
    after = _snapshot_sessions()
    new = after - before
    return next(iter(new), None)


def _read_profile_prompt(profile: str) -> str:
    agents_dir = Path(WORKSPACE) / "agents"
    prompt_file = agents_dir / f"{profile}.md"
    try:
        return prompt_file.read_text()
    except FileNotFoundError:
        logger.warning(f"No profile file for {profile}, using empty system prompt")
        return ""


def _parse_output(raw: str) -> tuple[str, list[str], list[dict], list[dict]]:
    """
    Split stdout into (chat_text, notifications, task_sentinels, artifact_sentinels).

    Sentinel formats emitted by agents:
      NOTIFY: <message>
      TASK: <profile> | <title> | <prompt> | auto=<true|false>
      ARTIFACT: <path> | <title>
    """
    lines = raw.splitlines()
    chat_lines: list[str] = []
    notifications: list[str] = []
    task_sentinels: list[dict] = []
    artifact_sentinels: list[dict] = []

    for line in lines:
        if line.startswith("NOTIFY:"):
            notifications.append(line[len("NOTIFY:"):].strip())

        elif line.startswith("TASK:"):
            # TASK: <profile> | <title> | <prompt> | auto=<bool>
            parts = [p.strip() for p in line[len("TASK:"):].split("|")]
            if len(parts) >= 3:
                auto_str = parts[3].lower() if len(parts) >= 4 else ""
                task_sentinels.append({
                    "assigned_to": parts[0],
                    "title": parts[1],
                    "prompt": parts[2],
                    "auto_execute": auto_str == "auto=true",
                })

        elif line.startswith("ARTIFACT:"):
            # ARTIFACT: <path> | <title>
            parts = [p.strip() for p in line[len("ARTIFACT:"):].split("|")]
            if parts:
                artifact_sentinels.append({
                    "path": parts[0],
                    "title": parts[1] if len(parts) > 1 else parts[0],
                })

        else:
            chat_lines.append(line)

    return "\n".join(chat_lines).strip(), notifications, task_sentinels, artifact_sentinels


def _build_command(profile: str, text: str, session_id: str | None) -> list[str]:
    cmd = ["claude", "-p", text]

    if session_id:
        cmd += ["--resume", session_id]

    cmd += ["--dangerously-skip-permissions"]

    profile_prompt = _read_profile_prompt(profile)
    if profile_prompt:
        cmd += ["--append-system-prompt", profile_prompt]

    tools = PROFILE_TOOLS.get(profile)
    if tools is not None:
        cmd += ["--allowed-tools", ",".join(tools)]

    mcp_path = PROFILE_MCP.get(profile)
    if mcp_path and os.path.exists(mcp_path):
        cmd += ["--mcp-config", mcp_path]

    return cmd


async def run(
    profile: str,
    text: str,
    session_id: str | None = None,
    cwd: str = WORKSPACE,
    timeout: int = 300,
) -> RunResult:
    """Run Claude CLI for a profile, return structured result."""
    before = _snapshot_sessions() if not session_id else set()
    cmd = _build_command(profile, text, session_id)

    logger.info(f"Running claude [{profile}] session={session_id or 'new'}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return RunResult(text="Timed out after 5 minutes.", session_id=session_id, returncode=1)
    except Exception as e:
        return RunResult(text=f"Error: {e}", session_id=session_id, returncode=1)

    raw = stdout.decode().strip() or stderr.decode().strip() or "Done (no output)."
    chat_text, notifications, task_sentinels, artifact_sentinels = _parse_output(raw)

    # Detect new session ID if this was a fresh run
    new_sid = session_id
    if not session_id:
        new_sid = _find_new_session(before)

    return RunResult(
        text=chat_text,
        session_id=new_sid,
        notifications=notifications,
        task_sentinels=task_sentinels,
        artifact_sentinels=artifact_sentinels,
        returncode=proc.returncode,
    )
