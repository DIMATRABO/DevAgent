"""
Persistent workflow task store.

Manages tasks/queue.json (the task registry) and tasks/workflows.json
(named multi-step pipeline definitions). Exposes CRUD + chaining helpers
that task_queue.py and the Telegram bot use to coordinate inter-agent work.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TASKS_DIR = Path("/workspace/tasks")
QUEUE_FILE = TASKS_DIR / "queue.json"
WORKFLOWS_FILE = TASKS_DIR / "workflows.json"
ARTIFACTS_DIR = TASKS_DIR / "artifacts"


# ── internal helpers ──────────────────────────────────────────────────────────

def _load_queue() -> list[dict]:
    try:
        return json.loads(QUEUE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_queue(tasks: list[dict]) -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(tasks, indent=2))


def _load_workflows() -> dict:
    try:
        return json.loads(WORKFLOWS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _next_wf_id(tasks: list[dict]) -> str:
    nums = [int(t["id"][3:]) for t in tasks if t["id"].startswith("WF-")]
    return f"WF-{(max(nums) + 1) if nums else 1:03d}"


# ── public API ────────────────────────────────────────────────────────────────

def create(
    title: str,
    prompt: str,
    created_by: str,
    assigned_to: str,
    workflow: str = "manual",
    step: int = 1,
    auto_execute: bool = False,
    priority: str = "normal",
    artifacts_in: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> dict:
    """Create and persist a new workflow task. Returns the task dict."""
    tasks = _load_queue()
    task = {
        "id": _next_wf_id(tasks),
        "title": title,
        "prompt": prompt,
        "created_by": created_by,
        "assigned_to": assigned_to,
        "workflow": workflow,
        "step": step,
        "status": "pending",
        "auto_execute": auto_execute,
        "priority": priority,
        "artifacts_in": artifacts_in or [],
        "artifacts_out": [],
        "dependencies": dependencies or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tasks.append(task)
    _save_queue(tasks)
    logger.info(f"Created workflow task {task['id']} [{assigned_to}]: {title}")
    return task


def get_task(task_id: str) -> dict | None:
    """Return a single task by WF-NNN id, or None."""
    return next((t for t in _load_queue() if t["id"] == task_id), None)


def list_pending(profile: str | None = None) -> list[dict]:
    """Return pending tasks, optionally filtered by assigned_to profile."""
    return [
        t for t in _load_queue()
        if t["status"] == "pending"
        and (profile is None or t["assigned_to"] == profile)
    ]


def list_all() -> list[dict]:
    """Return every task regardless of status."""
    return _load_queue()


def update_status(
    task_id: str,
    status: str,
    artifacts_out: list[str] | None = None,
) -> bool:
    """
    Update a task's status and optionally append produced artifact paths.
    Returns True if the task was found and updated.
    """
    tasks = _load_queue()
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = status
            if artifacts_out:
                t["artifacts_out"].extend(artifacts_out)
            _save_queue(tasks)
            logger.info(f"Task {task_id} → {status}")
            return True
    logger.warning(f"update_status: task {task_id} not found")
    return False


def get_next_step(workflow: str, current_step: int) -> dict | None:
    """
    Return the workflow step config for current_step+1, or None if there
    is no following step or the workflow is unknown.
    """
    workflows = _load_workflows()
    wf = workflows.get(workflow)
    if not wf:
        return None
    for step in wf["steps"]:
        if step["step"] == current_step + 1:
            return step
    return None
