"""
Channel registry for cross-interface notifications.
Interfaces register a send function at startup;
background tasks call notify() to reach the user.
"""

import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# user_id (str) -> async send function(message: str)
_channels: dict[str, Callable[[str], Awaitable[None]]] = {}


def register(user_id: str, send_fn: Callable[[str], Awaitable[None]]):
    """Register a send function for a user (called by each interface at startup)."""
    _channels[str(user_id)] = send_fn
    logger.debug(f"Registered notification channel for user {user_id}")


async def notify(user_id: str, message: str):
    """Send a notification to a user through their registered channel."""
    send_fn = _channels.get(str(user_id))
    if send_fn:
        try:
            await send_fn(message)
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
    else:
        logger.warning(f"No notification channel registered for user {user_id}")
