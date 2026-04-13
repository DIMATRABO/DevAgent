"""
Async background task registry.

Wraps asyncio.create_task so the Telegram bot can dispatch long-running
Claude jobs (Developer, Reviewer) without blocking message handling.
Done callbacks fire the notifier and auto-chain the Reviewer after a Developer PR.
"""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any

from core import notifier, claude_runner, session_store

logger = logging.getLogger(__name__)


@dataclass
class TaskInfo:
    task_id: str
    user_id: str
    profile: str
    description: str
    task: asyncio.Task
    status: str = "running"   # running | done | failed


# task_id -> TaskInfo
_registry: dict[str, TaskInfo] = {}


def _extract_pr_ref(notification: str) -> str | None:
    """Extract 'PR #N' or a PR URL from a NOTIFY message."""
    m = re.search(r"PR #(\d+)", notification)
    if m:
        return f"PR #{m.group(1)}"
    m = re.search(r"(https?://[^\s]+/pull/\d+)", notification)
    if m:
        return m.group(1)
    return None


async def _run_task(
    task_id: str,
    user_id: str,
    profile: str,
    text: str,
    session_id: str | None,
):
    """Execute a Claude run and handle completion callbacks."""
    try:
        result = await claude_runner.run(profile, text, session_id)

        # Persist new session ID
        if result.session_id and result.session_id != session_id:
            session_store.set_session(user_id, profile, result.session_id)

        _registry[task_id].status = "done" if result.returncode == 0 else "failed"

        # Send the full response as a notification
        if result.text:
            await notifier.notify(user_id, f"[{profile}] {result.text}")

        # Send any explicit NOTIFY lines
        for msg in result.notifications:
            await notifier.notify(user_id, msg)

            # Auto-chain: Developer opens PR → Reviewer auto-starts
            if profile == "developer":
                pr_ref = _extract_pr_ref(msg)
                if pr_ref:
                    logger.info(f"Auto-chaining reviewer for {pr_ref}")
                    reviewer_sid = session_store.get_session(user_id, "reviewer")
                    submit(
                        user_id=user_id,
                        profile="reviewer",
                        text=f"Review and merge {pr_ref}. If the code looks good, approve and merge. Output NOTIFY when done.",
                        session_id=reviewer_sid,
                        description=f"Auto-review {pr_ref}",
                    )

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        _registry[task_id].status = "failed"
        await notifier.notify(user_id, f"Background task failed: {e}")
    finally:
        # Clean up registry after a delay so /tasks can still show it briefly
        await asyncio.sleep(60)
        _registry.pop(task_id, None)


def submit(
    user_id: str,
    profile: str,
    text: str,
    session_id: str | None = None,
    description: str = "",
) -> str:
    """
    Submit a background Claude task. Returns task_id.
    Non-blocking — the caller gets an immediate task_id back.
    """
    task_id = str(uuid.uuid4())[:8]
    coro = _run_task(task_id, user_id, profile, text, session_id)
    asyncio_task = asyncio.create_task(coro)
    _registry[task_id] = TaskInfo(
        task_id=task_id,
        user_id=user_id,
        profile=profile,
        description=description or text[:60],
        task=asyncio_task,
    )
    logger.info(f"Submitted background task {task_id} [{profile}] for user {user_id}")
    return task_id


def list_running(user_id: str) -> list[TaskInfo]:
    return [t for t in _registry.values() if t.user_id == user_id and t.status == "running"]


def cancel(task_id: str) -> bool:
    info = _registry.get(task_id)
    if info and not info.task.done():
        info.task.cancel()
        info.status = "cancelled"
        return True
    return False
