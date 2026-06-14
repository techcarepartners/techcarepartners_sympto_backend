"""Internal / cron endpoints (protected by INTERNAL_SECRET bearer token)."""

from fastapi import APIRouter, Depends

from app.dependencies import verify_internal_token
from app.services.reminder_service import send_due_reminders

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_token)])


@router.post("/send-reminders")
async def trigger_reminders() -> dict:
    """
    Send appointment reminders for appointments 1.5–2.5 hours away.
    Called every 5 minutes by Supabase pg_cron or external scheduler.
    """
    result = await send_due_reminders()
    return result


@router.get("/health")
async def health_check() -> dict:
    """Internal health check."""
    return {"status": "ok"}
