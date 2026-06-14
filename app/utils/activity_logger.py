"""Activity logging to the activity_logs table."""

import asyncio
from typing import Any

from app.database import db_insert


async def log_event(
    event: str,
    role: str,
    phone_number: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget activity log entry."""
    try:
        await db_insert(
            "activity_logs",
            {
                "whatsapp_number": phone_number,
                "role": role,
                "event": event,
                "detail": detail or {},
            },
        )
    except Exception:
        pass  # never crash on logging failure
