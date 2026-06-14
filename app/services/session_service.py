"""Session state management for patient conversations."""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

from app.database import db_fetch_one, db_insert, db_update, db_upsert
from app.constants import PatientState
from app.config import get_settings

logger = logging.getLogger(__name__)


async def get_or_create_session(phone_number: str, role: str = "patient") -> dict:
    """Load existing conversation session or create a new IDLE one."""
    row = await db_fetch_one("conversations", {"whatsapp_number": phone_number})
    if row:
        # Check timeout
        settings = get_settings()
        updated = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - updated > timedelta(hours=settings.session_timeout_hours):
            await _reset_session(phone_number, end_reason="timeout")
            row = await db_fetch_one("conversations", {"whatsapp_number": phone_number})
        return row

    # Create new session
    new_row = await db_insert(
        "conversations",
        {
            "whatsapp_number": phone_number,
            "role": role,
            "state": PatientState.IDLE,
            "context": {},
        },
    )
    return new_row


async def update_session(phone_number: str, state: str, context: dict) -> None:
    """Persist new state + context for a patient session."""
    await db_update(
        "conversations",
        {"whatsapp_number": phone_number},
        {"state": state, "context": context, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


async def _reset_session(phone_number: str, end_reason: str = "reset") -> None:
    """Reset session to IDLE and close open analytics session."""
    session = await db_fetch_one("conversations", {"whatsapp_number": phone_number})
    if session:
        ctx = session.get("context", {})
        session_id = ctx.get("session_id")
        if session_id:
            await _close_analytics_session(session_id, session.get("state"), end_reason)

    await db_update(
        "conversations",
        {"whatsapp_number": phone_number},
        {
            "state": PatientState.IDLE,
            "context": {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


async def open_analytics_session(phone_number: str, patient_id: str) -> str:
    """Create a new conversation_sessions row and return its ID."""
    row = await db_insert(
        "conversation_sessions",
        {
            "whatsapp_number": phone_number,
            "context_snapshot": {},
        },
    )
    return row["id"]


async def close_analytics_session(
    session_id: str, final_state: str, end_reason: str, context_snapshot: dict | None = None
) -> None:
    await _close_analytics_session(session_id, final_state, end_reason, context_snapshot)


async def _close_analytics_session(
    session_id: str, final_state: str | None, end_reason: str, context_snapshot: dict | None = None
) -> None:
    try:
        await db_update(
            "conversation_sessions",
            {"id": session_id},
            {
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "final_state": final_state or PatientState.IDLE,
                "end_reason": end_reason,
                "context_snapshot": context_snapshot or {},
            },
        )
    except Exception as e:
        logger.warning("Failed to close analytics session %s: %s", session_id, e)
