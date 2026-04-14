"""
Async background task registry.

Wraps asyncio.create_task so the Telegram bot can dispatch long-running
Claude jobs without blocking message handling. Done callbacks fire the
notifier and chain the next workflow step via workflow_store.
"""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any

from core import notifier, claude_runner, session_store, workflow_store

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
    wf_task_id: str | None = None,
):
    """Execute a Claude run and handle completion callbacks."""
    try:
        result = await claude_runner.run(profile, text, session_id)

        # Persist new session ID
        if result.session_id and result.session_id != session_id:
            session_store.set_session(user_id, profile, result.session_id)

        final_status = "done" if result.returncode == 0 else "failed"
        _registry[task_id].status = final_status

        # Update workflow task status and attach produced artifacts
        if wf_task_id:
            artifact_paths = [a["path"] for a in result.artifact_sentinels] or None
            workflow_store.update_status(wf_task_id, final_status, artifact_paths)

        # Send the full response as a notification
        if result.text:
            await notifier.notify(user_id, f"[{profile}] {result.text}")

        # Log ARTIFACT sentinels
        for art in result.artifact_sentinels:
            logger.info(f"Artifact produced: {art['path']} — {art['title']}")

        # Process TASK sentinels — create WF tasks, auto-submit or notify user
        for ts in result.task_sentinels:
            new_wf = workflow_store.create(
                title=ts["title"],
                prompt=ts["prompt"],
                created_by=profile,
                assigned_to=ts["assigned_to"],
                workflow="manual",
                auto_execute=ts["auto_execute"],
            )
            if ts["auto_execute"]:
                next_sid = session_store.get_session(user_id, ts["assigned_to"])
                submit(
                    user_id=user_id,
                    profile=ts["assigned_to"],
                    text=ts["prompt"],
                    session_id=next_sid,
                    description=ts["title"],
                    wf_task_id=new_wf["id"],
                )
                logger.info(f"Auto-submitted {new_wf['id']} [{ts['assigned_to']}]: {ts['title']}")
            else:
                await notifier.notify(
                    user_id,
                    f"📋 Task ready for {ts['assigned_to']}: {ts['title']} — /approve {new_wf['id']} to run",
                )

        # Process NOTIFY lines
        for msg in result.notifications:
            await notifier.notify(user_id, msg)

            if wf_task_id:
                # Workflow-aware chaining: find next step defined in the pipeline
                wf_task = workflow_store.get_task(wf_task_id)
                pr_ref = _extract_pr_ref(msg)
                if wf_task and pr_ref:
                    next_step = workflow_store.get_next_step(wf_task["workflow"], wf_task["step"])
                    if next_step:
                        next_profile = next_step["profile"]
                        auto = next_step.get("auto", False)
                        next_wf = workflow_store.create(
                            title=f"Review {pr_ref}",
                            prompt=f"Review and merge {pr_ref}. Output NOTIFY when done.",
                            created_by=profile,
                            assigned_to=next_profile,
                            workflow=wf_task["workflow"],
                            step=next_step["step"],
                            auto_execute=auto,
                        )
                        if auto:
                            next_sid = session_store.get_session(user_id, next_profile)
                            submit(
                                user_id=user_id,
                                profile=next_profile,
                                text=next_wf["prompt"],
                                session_id=next_sid,
                                description=next_wf["title"],
                                wf_task_id=next_wf["id"],
                            )
                        else:
                            await notifier.notify(
                                user_id,
                                f"📋 Task ready for {next_profile}: Review {pr_ref} — /approve {next_wf['id']} to run",
                            )
            elif profile == "developer":
                # Legacy auto-chain: Developer opens PR → Reviewer auto-starts
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
        if wf_task_id:
            workflow_store.update_status(wf_task_id, "failed")
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
    wf_task_id: str | None = None,
) -> str:
    """
    Submit a background Claude task. Returns task_id immediately.
    Pass wf_task_id to link execution to a workflow_store entry.
    """
    task_id = str(uuid.uuid4())[:8]
    coro = _run_task(task_id, user_id, profile, text, session_id, wf_task_id)
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
