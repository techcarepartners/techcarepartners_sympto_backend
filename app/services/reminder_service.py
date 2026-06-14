"""Reminder system — sends reminders 2 hours before confirmed appointments."""

import asyncio
import logging
from datetime import datetime, timezone

from app.database import get_supabase, db_update
from app.services.notification_service import send_reminder_to_patient, send_reminder_to_doctor
from app.utils.slot_utils import format_appointment_time_ist
from app.utils.activity_logger import log_event

logger = logging.getLogger(__name__)


async def send_due_reminders() -> dict:
    """
    Fetch appointments due for a reminder (1.5h – 2.5h from now) and send them.
    Called by /internal/send-reminders every 5 minutes.
    Returns summary of sent/failed counts.
    """
    client = get_supabase()

    def _fetch():
        # Using Supabase RPC or raw query for time-window filtering
        return (
            client.table("appointments")
            .select(
                "id, slot_day, slot_window, appointment_time, urgency, "
                "patients(whatsapp_number, name, language), "
                "doctors(whatsapp_number, name)"
            )
            .eq("status", "confirmed")
            .eq("reminder_sent", False)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    rows = result.data or []

    now = datetime.now(timezone.utc)
    due = []
    for row in rows:
        appt_time_str = row.get("appointment_time")
        if not appt_time_str:
            continue
        appt_time = datetime.fromisoformat(appt_time_str.replace("Z", "+00:00"))
        delta_minutes = (appt_time - now).total_seconds() / 60
        if 90 <= delta_minutes <= 150:
            due.append((row, appt_time))

    sent = 0
    failed = 0

    for row, appt_time in due:
        appt_id = row["id"]
        patient = row.get("patients") or {}
        doctor = row.get("doctors") or {}

        patient_phone = patient.get("whatsapp_number", "")
        patient_name = patient.get("name", "")
        patient_lang = patient.get("language") or "english"
        doctor_phone = doctor.get("whatsapp_number", "")
        doctor_name = doctor.get("name", "")
        time_str = format_appointment_time_ist(appt_time)

        try:
            await send_reminder_to_patient(patient_phone, patient_lang, doctor_name, time_str)
            await send_reminder_to_doctor(doctor_phone, patient_name, time_str)
            await db_update("appointments", {"id": appt_id}, {"reminder_sent": True})
            await log_event(
                "reminder_sent",
                role="system",
                detail={
                    "appointment_id": appt_id,
                    "patient_number": patient_phone,
                    "doctor_number": doctor_phone,
                    "appointment_time": time_str,
                },
            )
            sent += 1
        except Exception as e:
            logger.error("Failed to send reminder for appointment %s: %s", appt_id, e)
            await log_event(
                "reminder_failed",
                role="system",
                detail={"appointment_id": appt_id, "error": str(e)},
            )
            failed += 1

    return {"sent": sent, "failed": failed, "total_checked": len(rows)}
