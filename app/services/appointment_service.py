"""Appointment creation, confirmation, rejection, and cancellation."""

import asyncio
import logging
from datetime import datetime, timezone

from app.database import db_fetch_one, db_fetch_many, db_insert, db_update
from app.utils.slot_utils import compute_appointment_time

logger = logging.getLogger(__name__)


async def create_appointment(
    patient_id: str,
    doctor_id: str,
    slot_day: str,
    slot_window: str,
    clinic_id: str | None,
    symptoms_summary: str | None,
    urgency: str,
) -> dict:
    """Create a new pending appointment. Raises ValueError on duplicate."""
    # Check for duplicate booking
    existing = await _find_duplicate(patient_id, doctor_id, slot_day)
    if existing:
        doctor = await db_fetch_one("doctors", {"id": doctor_id})
        raise ValueError(
            f"duplicate:{doctor['name']}:{slot_day}"
        )

    row = await db_insert(
        "appointments",
        {
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "clinic_id": clinic_id,
            "slot_day": slot_day,
            "slot_window": slot_window,
            "symptoms_summary": symptoms_summary,
            "urgency": urgency,
            "status": "pending",
        },
    )
    return row


async def confirm_appointment(appointment_id: str) -> dict:
    """Confirm an appointment and compute appointment_time."""
    appt = await db_fetch_one("appointments", {"id": appointment_id})
    if not appt:
        raise ValueError("Appointment not found")

    appointment_time = compute_appointment_time(appt["slot_day"], appt["slot_window"])
    updated = await db_update(
        "appointments",
        {"id": appointment_id},
        {
            "status": "confirmed",
            "appointment_time": appointment_time.isoformat(),
        },
    )
    return updated[0] if updated else appt


async def cancel_appointment(appointment_id: str) -> dict:
    """Cancel an appointment by ID."""
    updated = await db_update(
        "appointments",
        {"id": appointment_id},
        {"status": "cancelled"},
    )
    if not updated:
        raise ValueError("Appointment not found or already cancelled")
    return updated[0]


async def get_patient_appointments(patient_id: str, active_only: bool = False) -> list[dict]:
    """Fetch patient appointments with doctor and clinic info."""
    client_rows = await _fetch_appointments_with_details(
        filters={"patient_id": patient_id}, active_only=active_only, limit=10
    )
    return client_rows


async def get_doctor_appointments(doctor_id: str) -> list[dict]:
    """Fetch all doctor appointments with patient info."""
    return await _fetch_appointments_with_details(
        filters={"doctor_id": doctor_id}, active_only=False, limit=50
    )


async def _find_duplicate(patient_id: str, doctor_id: str, slot_day: str) -> dict | None:
    """Check for existing pending/confirmed booking at same slot_day."""
    import asyncio
    from app.database import get_supabase

    client = get_supabase()

    def _fetch():
        return (
            client.table("appointments")
            .select("id")
            .eq("patient_id", patient_id)
            .eq("doctor_id", doctor_id)
            .eq("slot_day", slot_day)
            .in_("status", ["pending", "confirmed"])
            .limit(1)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    return result.data[0] if result.data else None


async def _fetch_appointments_with_details(
    filters: dict, active_only: bool, limit: int
) -> list[dict]:
    """Fetch appointments joined with doctor + patient + clinic data."""
    from app.database import get_supabase

    client = get_supabase()

    def _fetch():
        q = (
            client.table("appointments")
            .select("*, doctors(name, specialization), patients(name, age, gender, phone_number:whatsapp_number), clinics(clinic_name, city)")
            .order("created_at", desc=True)
            .limit(limit)
        )
        for key, val in filters.items():
            q = q.eq(key, val)
        if active_only:
            q = q.in_("status", ["pending", "confirmed"])
        return q.execute()

    result = await asyncio.to_thread(_fetch)
    rows = result.data or []

    enriched = []
    for row in rows:
        doc = row.pop("doctors", {}) or {}
        pat = row.pop("patients", {}) or {}
        clinic = row.pop("clinics", {}) or {}
        row["doctor_name"] = doc.get("name", "")
        row["doctor_specialization"] = doc.get("specialization", "")
        row["patient_name"] = pat.get("name", "")
        row["patient_age"] = pat.get("age", 0)
        row["patient_gender"] = pat.get("gender", "")
        row["patient_phone"] = pat.get("phone_number", "")
        row["clinic_name"] = clinic.get("clinic_name", "")
        row["clinic_city"] = clinic.get("city", "")
        enriched.append(row)

    return enriched
