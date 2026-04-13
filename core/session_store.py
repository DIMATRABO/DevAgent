"""
Per-user, per-profile session and profile state.
Persists to ~/.claude/devagent_sessions.json.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SESSIONS_FILE = Path.home() / ".claude" / "devagent_sessions.json"
DEFAULT_PROFILE = "developer"

# In-memory state
_sessions: dict[str, str] = {}   # "uid:profile" -> session_id
_profiles: dict[str, str] = {}   # "uid" -> current_profile


def _load():
    global _sessions, _profiles
    try:
        data = json.loads(SESSIONS_FILE.read_text())
        _sessions = data.get("sessions", {})
        _profiles = data.get("profiles", {})
    except (FileNotFoundError, json.JSONDecodeError):
        _sessions = {}
        _profiles = {}


def _save():
    try:
        SESSIONS_FILE.write_text(json.dumps({"sessions": _sessions, "profiles": _profiles}))
    except Exception as e:
        logger.error(f"Failed to save sessions: {e}")


def init():
    _load()
    logger.info(f"Loaded {len(_sessions)} sessions, {len(_profiles)} profile assignments")


def get_session(user_id: str, profile: str) -> str | None:
    return _sessions.get(f"{user_id}:{profile}")


def set_session(user_id: str, profile: str, session_id: str):
    _sessions[f"{user_id}:{profile}"] = session_id
    _save()


def delete_session(user_id: str, profile: str):
    _sessions.pop(f"{user_id}:{profile}", None)
    _save()


def get_profile(user_id: str) -> str:
    return _profiles.get(str(user_id), DEFAULT_PROFILE)


def set_profile(user_id: str, profile: str):
    _profiles[str(user_id)] = profile
    _save()
