"""Doctor API endpoints."""

import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_doctor
from app.database import db_fetch_one, db_fetch_many, db_update, db_insert, db_upsert, db_delete, get_supabase
from app.schemas.doctor import (
    DoctorRegisterRequest,
    DoctorUpdateProfileRequest,
    ClinicRequest,
    UpdateAvailabilityRequest,
    VacationRequest,
    VacationCreateRequest,
    VacationUpdateRequest,
    AppointmentActionRequest,
    DoctorProfileResponse,
    ClinicResponse,
    DoctorAppointmentResponse,
)
from app.services.appointment_service import (
    confirm_appointment,
    cancel_appointment,
    get_doctor_appointments,
)
from app.services.notification_service import (
    notify_patient_appointment_confirmed,
    notify_patient_appointment_rejected,
    create_notification,
)
from app.services.session_service import get_or_create_session, update_session
from app.utils.slot_utils import build_available_slots_from_days_times
from app.utils.messages import DOCTOR_MESSAGES
from app.utils.activity_logger import log_event
from app.constants import DoctorState, PatientState, VALID_SPECIALIZATIONS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/doctor", tags=["doctor"])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _get_clinics(doctor_id: str) -> list[dict]:
    """Return all active clinics for a doctor."""
    return await db_fetch_many(
        "clinics",
        {"doctor_id": doctor_id, "is_active": True},
        order_by="created_at",
    )


def _format_clinic(clinic: dict) -> dict:
    """Format a clinic row for API response."""
    return {
        "id": clinic.get("id", ""),
        "clinic_name": clinic.get("clinic_name", ""),
        "city": clinic.get("city", ""),
        "state": clinic.get("state", ""),
        "pincode": clinic.get("pincode", ""),
        "address": clinic.get("address", ""),
        "maps": clinic.get("maps", ""),
        "available_slots": clinic.get("available_slots") or [],
        "is_active": clinic.get("is_active", True),
    }


def _format_appt_for_doctor(appt: dict) -> dict:
    """Format an appointment row for the doctor dashboard."""
    return {
        "id": appt.get("id"),
        "patient_id": appt.get("patient_id"),
        "patient_name": appt.get("patient_name", ""),
        "slot_day": appt.get("slot_day", ""),
        "slot_window": appt.get("slot_window", ""),
        "appointment_time": appt.get("appointment_time"),
        "status": appt.get("status", "pending"),
        "symptoms_summary": appt.get("symptoms_summary", ""),
        "clinic_id": appt.get("clinic_id"),
        "clinic_name": appt.get("clinic_name", ""),
        "created_at": appt.get("created_at"),
    }



# ---------------------------------------------------------------------------
# Registration & Profile
# ---------------------------------------------------------------------------

@router.post("/register")
async def register_doctor(
    body: DoctorRegisterRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Register or update doctor profile + create/update clinic."""
    if body.specialization not in VALID_SPECIALIZATIONS:
        raise HTTPException(400, f"Invalid specialization. Choose from: {sorted(VALID_SPECIALIZATIONS)}")

    available_slots = build_available_slots_from_days_times(body.available_days, body.time_slots)

    # Upsert doctor record
    doctor_update: dict = {
        "name": body.name.strip(),
        "registration_number": body.registration_number,
        "year_register": body.year_register,
        "specialization": body.specialization,
    }
    if body.email:
        doctor_update["email"] = body.email.strip().lower()
    await db_update("doctors", {"id": doctor["id"]}, doctor_update)

    # Insert clinic (always create new on first registration; update existing on re-registration)
    existing_clinics = await _get_clinics(doctor["id"])
    if not existing_clinics:
        await db_insert(
            "clinics",
            {
                "doctor_id": doctor["id"],
                "clinic_name": body.clinic_name,
                "city": body.city,
                "state": body.state,
                "pincode": body.pincode,
                "address": body.address,
                "maps": body.maps,
                "available_slots": available_slots,
            },
        )
    else:
        # Update first active clinic
        await db_update(
            "clinics",
            {"id": existing_clinics[0]["id"]},
            {
                "clinic_name": body.clinic_name,
                "city": body.city,
                "state": body.state,
                "pincode": body.pincode,
                "address": body.address,
                "maps": body.maps,
                "available_slots": available_slots,
            },
        )

    # Update multi_clinic flag
    all_clinics = await _get_clinics(doctor["id"])
    if len(all_clinics) >= 2:
        await db_update("doctors", {"id": doctor["id"]}, {"multi_clinic": True})

    await log_event(
        "doctor_registration_complete", "doctor",
        phone_number=doctor["whatsapp_number"],
        detail={"name": body.name, "specialization": body.specialization, "city": body.city, "clinic_name": body.clinic_name},
    )

    return {"message": DOCTOR_MESSAGES["ONBOARDING_DONE"]}


@router.get("/profile", response_model=DoctorProfileResponse)
async def get_doctor_profile(doctor: dict = Depends(get_current_doctor)) -> DoctorProfileResponse:
    """Return doctor profile with all clinics."""
    clinics = await _get_clinics(doctor["id"])
    return DoctorProfileResponse(
        id=doctor["id"],
        phone_number=doctor["whatsapp_number"],
        name=doctor.get("name", ""),
        email=doctor.get("email"),
        registration_number=doctor.get("registration_number"),
        year_register=doctor.get("year_register"),
        specialization=doctor.get("specialization", ""),
        photo_url=doctor.get("photo_url"),
        is_approved=doctor.get("is_approved", False),
        is_member=doctor.get("is_member", False),
        multi_clinic=doctor.get("multi_clinic", False),
        vacation_start=doctor.get("vacation_start"),
        vacation_end=doctor.get("vacation_end"),
        vacation_reason=doctor.get("vacation_reason"),
        registered_at=doctor.get("registered_at", ""),
        clinics=[_format_clinic(c) for c in clinics],
    )


@router.post("/update-profile")
async def update_doctor_profile(
    body: DoctorUpdateProfileRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Update name and/or specialization only."""
    update_data = {}
    if body.name:
        update_data["name"] = body.name.strip()
    if body.specialization:
        spec = body.specialization.lower()
        if spec not in VALID_SPECIALIZATIONS:
            raise HTTPException(400, "Invalid specialization")
        update_data["specialization"] = spec

    if update_data:
        await db_update("doctors", {"id": doctor["id"]}, update_data)

    return {"message": "Profile updated"}


# ---------------------------------------------------------------------------
# Availability & Clinics
# ---------------------------------------------------------------------------

@router.post("/update-availability")
async def update_availability(
    body: UpdateAvailabilityRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Update doctor's available slots."""
    new_slots = build_available_slots_from_days_times(body.available_days, body.time_slots)
    clinics = await _get_clinics(doctor["id"])

    if body.clinic_id and not body.update_all:
        # Update single clinic
        target = next((c for c in clinics if c["id"] == body.clinic_id), None)
        if not target:
            raise HTTPException(404, "Clinic not found")
        await db_update("clinics", {"id": body.clinic_id}, {"available_slots": new_slots})
        await log_event("doctor_availability_updated_single", "doctor", doctor["whatsapp_number"], {"clinic_id": body.clinic_id})
    else:
        # Update all clinics
        for clinic in clinics:
            await db_update("clinics", {"id": clinic["id"]}, {"available_slots": new_slots})
        await log_event("doctor_availability_updated_all", "doctor", doctor["whatsapp_number"])

    return {"message": DOCTOR_MESSAGES["AVAILABILITY_UPDATED"]}


def _build_slots_from_request(body: ClinicRequest) -> list[dict]:
    """Build available_slots from either new schedule format or legacy days/times."""
    if body.schedule:
        result = []
        window_map = {
            range(0, 13): "9am - 1pm",
            range(13, 17): "1pm - 5pm",
            range(17, 24): "5pm - 9pm",
        }
        for s in body.schedule:
            day = s.get("day", "")
            start = s.get("start", "")
            end = s.get("end", "")
            if not (day and start and end):
                continue
            h = int(start.split(":")[0])
            window = next((v for r, v in window_map.items() if h in r), "9am - 1pm")
            result.append({"day": day, "start": start, "end": end, "window": window})
        return result
    return build_available_slots_from_days_times(body.available_days, body.time_slots)


@router.post("/clinic")
async def add_clinic(
    body: ClinicRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Add a new clinic for the doctor."""
    available_slots = _build_slots_from_request(body)
    await db_insert(
        "clinics",
        {
            "doctor_id": doctor["id"],
            "clinic_name": body.clinic_name,
            "city": body.city,
            "state": body.state,
            "pincode": body.pincode,
            "address": body.address,
            "maps": body.maps,
            "available_slots": available_slots,
        },
    )
    all_clinics = await _get_clinics(doctor["id"])
    if len(all_clinics) >= 2:
        await db_update("doctors", {"id": doctor["id"]}, {"multi_clinic": True})

    await log_event("doctor_clinic_added", "doctor", doctor["whatsapp_number"], {"clinic_name": body.clinic_name, "city": body.city})
    return {"message": DOCTOR_MESSAGES["CLINIC_ADDED"]}


@router.put("/clinic/{clinic_id}")
async def update_clinic(
    clinic_id: str,
    body: ClinicRequest,
    doctor: dict = Depends(get_current_doctor),
) -> dict:
    """Update an existing clinic."""
    clinic = await db_fetch_one("clinics", {"id": clinic_id})
    if not clinic or clinic["doctor_id"] != doctor["id"]:
        raise HTTPException(404, "Clinic not found")

    new_slots = _build_slots_from_request(body)
    await db_update(
        "clinics",
        {"id": clinic_id},
        {
            "clinic_name": body.clinic_name,
            "city": body.city,
            "state": body.state,
            "pincode": body.pincode,
            "address": body.address,
            "maps": body.maps,
            "available_slots": new_slots,
        },
    )
    return {"message": "Clinic updated"}


@router.delete("/clinic/{clinic_id}")
async def delete_clinic(
    clinic_id: str, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Soft-delete (archive) a clinic."""
    from datetime import datetime, timezone
    clinic = await db_fetch_one("clinics", {"id": clinic_id})
    if not clinic or clinic["doctor_id"] != doctor["id"]:
        raise HTTPException(404, "Clinic not found")

    await db_update(
        "clinics",
        {"id": clinic_id},
        {"is_active": False, "archived_at": datetime.now(timezone.utc).isoformat()},
    )
    # Update multi_clinic flag
    active = [c for c in await _get_clinics(doctor["id"]) if c["is_active"]]
    await db_update("doctors", {"id": doctor["id"]}, {"multi_clinic": len(active) >= 2})
    return {"message": "Clinic archived"}


# ---------------------------------------------------------------------------
# Vacation
# ---------------------------------------------------------------------------

@router.post("/vacation")
async def set_vacation(
    body: VacationRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Set or update vacation dates."""
    if body.vacation_end < body.vacation_start:
        raise HTTPException(400, DOCTOR_MESSAGES["VACATION_INVALID_DATES"])

    await db_update(
        "doctors",
        {"id": doctor["id"]},
        {"vacation_start": body.vacation_start, "vacation_end": body.vacation_end, "vacation_reason": body.vacation_reason or "On Vacation"},
    )
    return {
        "message": DOCTOR_MESSAGES["VACATION_SAVED"].format(
            start=body.vacation_start, end=body.vacation_end
        )
    }


@router.delete("/vacation")
async def cancel_vacation(doctor: dict = Depends(get_current_doctor)) -> dict:
    """Clear vacation dates."""
    await db_update(
        "doctors",
        {"id": doctor["id"]},
        {"vacation_start": None, "vacation_end": None},
    )
    return {"message": DOCTOR_MESSAGES["VACATION_CANCELLED"]}


# ---------------------------------------------------------------------------
# Multiple vacations (doctor_vacations table)
# ---------------------------------------------------------------------------

@router.get("/vacations")
async def list_vacations(doctor: dict = Depends(get_current_doctor)) -> list:
    """List all vacation ranges for this doctor."""
    rows = await db_fetch_many(
        "doctor_vacations",
        filters={"doctor_id": doctor["id"]},
        order_by="vacation_start",
    )
    return rows


@router.post("/vacations")
async def create_vacation(
    body: VacationCreateRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Add a new vacation range."""
    if body.vacation_end < body.vacation_start:
        raise HTTPException(400, "vacation_end must be >= vacation_start")
    row = await db_insert("doctor_vacations", {
        "doctor_id": doctor["id"],
        "vacation_start": body.vacation_start,
        "vacation_end": body.vacation_end,
        "vacation_reason": body.vacation_reason or "On Vacation",
    })
    return row


@router.put("/vacations/{vacation_id}")
async def update_vacation(
    vacation_id: str,
    body: VacationUpdateRequest,
    doctor: dict = Depends(get_current_doctor),
) -> dict:
    """Update an existing vacation range (ownership checked)."""
    existing = await db_fetch_one("doctor_vacations", {"id": vacation_id})
    if not existing or existing["doctor_id"] != doctor["id"]:
        raise HTTPException(404, "Vacation not found")

    updates: dict = {}
    if body.vacation_start is not None:
        updates["vacation_start"] = body.vacation_start
    if body.vacation_end is not None:
        updates["vacation_end"] = body.vacation_end
    if body.vacation_reason is not None:
        updates["vacation_reason"] = body.vacation_reason

    start = updates.get("vacation_start", existing["vacation_start"])
    end = updates.get("vacation_end", existing["vacation_end"])
    if end < start:
        raise HTTPException(400, "vacation_end must be >= vacation_start")

    if not updates:
        return existing

    rows = await db_update("doctor_vacations", {"id": vacation_id}, updates)
    return rows[0] if rows else existing


@router.delete("/vacations/{vacation_id}")
async def delete_vacation(
    vacation_id: str,
    doctor: dict = Depends(get_current_doctor),
) -> dict:
    """Delete a vacation range (ownership checked)."""
    existing = await db_fetch_one("doctor_vacations", {"id": vacation_id})
    if not existing or existing["doctor_id"] != doctor["id"]:
        raise HTTPException(404, "Vacation not found")
    await db_delete("doctor_vacations", {"id": vacation_id})
    return {"message": "Vacation deleted"}


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

@router.get("/appointments")
async def get_appointments(doctor: dict = Depends(get_current_doctor)) -> dict:
    """Return all doctor appointments grouped by status."""
    appts = await get_doctor_appointments(doctor["id"])
    await log_event(
        "doctor_upcoming_appointments_viewed", "doctor",
        phone_number=doctor["whatsapp_number"],
        detail={
            "doctor_id": doctor["id"],
            "pending": sum(1 for a in appts if a["status"] == "pending"),
            "confirmed": sum(1 for a in appts if a["status"] == "confirmed"),
            "cancelled": sum(1 for a in appts if a["status"] == "cancelled"),
        },
    )
    return {
        "pending": [_format_appt_for_doctor(a) for a in appts if a["status"] == "pending"],
        "confirmed": [_format_appt_for_doctor(a) for a in appts if a["status"] == "confirmed"],
        "cancelled": [_format_appt_for_doctor(a) for a in appts if a["status"] == "cancelled"],
    }


@router.post("/confirm")
async def confirm(
    body: AppointmentActionRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Confirm an appointment and notify the patient."""
    appt = await db_fetch_one("appointments", {"id": body.appointment_id})
    if not appt or appt["doctor_id"] != doctor["id"]:
        raise HTTPException(404, "Appointment not found")
    if appt["status"] != "pending":
        raise HTTPException(400, f"Appointment is already {appt['status']}")

    confirmed = await confirm_appointment(body.appointment_id)

    # Persist the chosen appointment_time if provided
    if body.appointment_time:
        try:
            confirmed = await db_update(
                "appointments",
                {"id": body.appointment_id},
                {"appointment_time": body.appointment_time},
            )
            confirmed = confirmed[0] if confirmed else confirmed
        except Exception:
            pass

    patient = await db_fetch_one("patients", {"id": appt["patient_id"]})
    clinic = await db_fetch_one("clinics", {"id": appt["clinic_id"]}) if appt.get("clinic_id") else None

    if patient:
        await notify_patient_appointment_confirmed(
            patient_id=patient["id"],
            patient_phone=patient["whatsapp_number"],
            patient_language=patient.get("language") or "english",
            doctor_name=doctor["name"],
            slot_day=appt["slot_day"],
            slot_window=appt["slot_window"],
            clinic_name=clinic["clinic_name"] if clinic else "",
        )
        # Update patient session to SHOWING_MENU
        try:
            session = await get_or_create_session(patient["whatsapp_number"])
            ctx = session.get("context", {})
            if ctx.get("session_id"):
                from app.services.session_service import close_analytics_session
                await close_analytics_session(ctx["session_id"], session["state"], "confirmed", ctx)
            await update_session(patient["whatsapp_number"], PatientState.SHOWING_MENU, ctx)
        except Exception:
            pass

    if patient:
        await create_notification(
            recipient_role="patient",
            recipient_id=patient["id"],
            type="appointment_confirmed",
            title="Appointment Confirmed ✅",
            body=f"Dr. {doctor['name']} confirmed your {appt['slot_day']} ({appt['slot_window']}) appointment.",
            metadata={"appointment_id": body.appointment_id},
        )

    await log_event(
        "doctor_confirmed_appointment", "doctor",
        phone_number=doctor["whatsapp_number"],
        detail={
            "appointment_id": body.appointment_id,
            "patient_number": patient["whatsapp_number"] if patient else "",
            "patient_name": patient["name"] if patient else "",
            "slot_day": appt["slot_day"],
            "slot_window": appt["slot_window"],
            "appointment_time": confirmed.get("appointment_time"),
        },
    )

    return {
        "message": DOCTOR_MESSAGES["CONFIRMATION_TO_DOCTOR"],
        "appointment": confirmed,
    }


@router.post("/reject")
async def reject(
    body: AppointmentActionRequest, doctor: dict = Depends(get_current_doctor)
) -> dict:
    """Reject an appointment and notify the patient."""
    appt = await db_fetch_one("appointments", {"id": body.appointment_id})
    if not appt or appt["doctor_id"] != doctor["id"]:
        raise HTTPException(404, "Appointment not found")
    if appt["status"] not in ("pending", "confirmed"):
        raise HTTPException(400, f"Appointment is already {appt['status']}")

    cancelled = await cancel_appointment(body.appointment_id)

    rejected = cancelled

    patient = await db_fetch_one("patients", {"id": appt["patient_id"]})
    if patient:
        try:
            await notify_patient_appointment_rejected(
                patient_id=patient["id"],
                patient_phone=patient["whatsapp_number"],
                patient_language=patient.get("language") or "english",
                doctor_name=doctor["name"],
                slot_day=appt["slot_day"],
                slot_window=appt["slot_window"],
            )
            await create_notification(
                recipient_role="patient",
                recipient_id=patient["id"],
                type="appointment_rejected",
                title="Appointment Update",
                body="Your appointment request has been rejected.",
            )
        except Exception as e:
            logger.warning("Reject notification failed: %s", e)

    return {"message": DOCTOR_MESSAGES["REJECTION_TO_DOCTOR"], "appointment": rejected}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@router.get("/notifications")
async def get_doctor_notifications(doctor: dict = Depends(get_current_doctor)) -> dict:
    """Return unread notifications for this doctor."""
    rows = await db_fetch_many(
        "notifications",
        {"recipient_role": "doctor", "recipient_id": doctor["id"]},
        order_by="-created_at",
        limit=50,
    )
    return {"notifications": rows, "unread_count": sum(1 for r in rows if not r.get("is_read"))}


@router.post("/notifications/mark-read")
async def mark_doctor_notifications_read(doctor: dict = Depends(get_current_doctor)) -> dict:
    """Mark all unread notifications as read for this doctor."""
    from app.database import db_update_where
    await db_update_where(
        "notifications",
        {"recipient_role": "doctor", "recipient_id": doctor["id"], "is_read": False},
        {"is_read": True},
    )
    return {"message": "Marked as read"}
