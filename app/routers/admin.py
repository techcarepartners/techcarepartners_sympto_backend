"""Admin API endpoints (protected by INTERNAL_SECRET bearer token)."""

import logging
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_internal_token
from app.database import db_fetch_one, db_update, db_fetch_many, get_supabase
from app.schemas.admin import ApproveDoctorRequest, SetMembershipRequest, AdminAppointmentActionRequest
from app.services.notification_service import notify_doctor_approved, notify_doctor_membership_changed, create_notification
from app.services.appointment_service import confirm_appointment, cancel_appointment
from app.utils.activity_logger import log_event

import asyncio

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(verify_internal_token)])


@router.get("/pending-doctors")
async def list_pending_doctors() -> dict:
    """List unapproved doctors, split by profile completeness."""
    client = get_supabase()

    def _fetch_all():
        return (
            client.table("doctors")
            .select("*, clinics(*)")
            .eq("is_approved", False)
            .eq("is_rejected", False)
            .order("registered_at", desc=False)
            .execute()
        )

    result = await asyncio.to_thread(_fetch_all)
    all_docs = result.data or []

    # Split in Python — reliable regardless of PostgREST filter quirks
    pending    = [d for d in all_docs if d.get("name") and str(d["name"]).strip()]
    incomplete = [d for d in all_docs if not (d.get("name") and str(d["name"]).strip())]

    return {
        "pending_doctors":    pending,
        "incomplete_doctors": incomplete,
        "count":              len(pending),
    }


@router.post("/approve-doctor")
async def approve_doctor(body: ApproveDoctorRequest) -> dict:
    """Approve or reject a doctor application."""
    doctor = await db_fetch_one("doctors", {"id": body.doctor_id})
    if not doctor:
        raise HTTPException(404, "Doctor not found")

    if body.approved:
        await db_update("doctors", {"id": body.doctor_id}, {"is_approved": True, "is_rejected": False})
    else:
        await db_update("doctors", {"id": body.doctor_id}, {"is_approved": False, "is_rejected": True})

    if body.notify:
        await notify_doctor_approved(doctor["whatsapp_number"], body.approved)

    event = "doctor_approved" if body.approved else "doctor_rejected_admin"
    await log_event(event, "system", detail={"doctor_id": body.doctor_id, "name": doctor["name"]})

    await create_notification(
        recipient_role="doctor",
        recipient_id=body.doctor_id,
        type="doctor_approved" if body.approved else "doctor_rejected",
        title="Application Approved ✅" if body.approved else "Application Update",
        body=f"Your Sympto registration has been {'approved! You can now receive patients.' if body.approved else 'not approved at this time.'}",
        metadata={"doctor_id": body.doctor_id},
    )

    action = "approved" if body.approved else "rejected"
    return {"message": f"Doctor {action} successfully", "doctor_id": body.doctor_id}


@router.post("/set-membership")
async def set_membership(body: SetMembershipRequest) -> dict:
    """Grant or revoke premium membership for a doctor."""
    doctor = await db_fetch_one("doctors", {"id": body.doctor_id})
    if not doctor:
        raise HTTPException(404, "Doctor not found")

    await db_update("doctors", {"id": body.doctor_id}, {"is_member": body.is_member})

    if body.notify:
        await notify_doctor_membership_changed(doctor["whatsapp_number"], body.is_member)

    action = "granted" if body.is_member else "revoked"
    return {"message": f"Membership {action} successfully", "doctor_id": body.doctor_id}


@router.post("/confirm-appointment")
async def admin_confirm_appointment(body: AdminAppointmentActionRequest) -> dict:
    """Admin/dev: force-confirm an appointment."""
    confirmed = await confirm_appointment(body.appointment_id)
    return {"message": "Appointment confirmed", "appointment": confirmed}


@router.post("/reject-appointment")
async def admin_reject_appointment(body: AdminAppointmentActionRequest) -> dict:
    """Admin/dev: force-reject/cancel an appointment."""
    cancelled = await cancel_appointment(body.appointment_id)
    return {"message": "Appointment cancelled", "appointment": cancelled}


@router.get("/stats")
async def get_stats() -> dict:
    """Return basic platform statistics."""
    client = get_supabase()

    def _fetch_all():
        patients = client.table("patients").select("id", count="exact").execute()
        doctors = client.table("doctors").select("id", count="exact").execute()
        approved = client.table("doctors").select("id", count="exact").eq("is_approved", True).execute()
        pending_appts = client.table("appointments").select("id", count="exact").eq("status", "pending").execute()
        confirmed_appts = client.table("appointments").select("id", count="exact").eq("status", "confirmed").execute()
        return {
            "total_patients": patients.count,
            "total_doctors": doctors.count,
            "approved_doctors": approved.count,
            "pending_appointments": pending_appts.count,
            "confirmed_appointments": confirmed_appts.count,
        }

    stats = await asyncio.to_thread(_fetch_all)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/notifications")
async def get_admin_notifications() -> list:
    """Fetch recent admin-level notifications (new registrations, etc)."""
    client = get_supabase()

    def _fetch():
        return (
            client.table("notifications")
            .select("*")
            .eq("recipient_role", "admin")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    return result.data or []


@router.post("/notifications/mark-read")
async def mark_admin_notifications_read() -> dict:
    """Mark all unread admin notifications as read."""
    client = get_supabase()

    def _update():
        return (
            client.table("notifications")
            .update({"is_read": True})
            .eq("recipient_role", "admin")
            .eq("is_read", False)
            .execute()
        )

    await asyncio.to_thread(_update)
    return {"message": "Marked as read"}


# ─────────────────────────────────────────────────────────────────────────────
# List endpoints for dashboard
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/doctors")
async def list_doctors() -> dict:
    """Return all doctors enriched with their primary clinic data."""
    from app.database import db_fetch_many
    doctors = await db_fetch_many("doctors", order_by="-registered_at")
    clinics = await db_fetch_many("clinics", {"is_active": True})
    # Build a lookup: doctor_id -> first active clinic
    clinic_map = {}
    for c in clinics:
        did = c["doctor_id"]
        if did not in clinic_map:
            clinic_map[did] = c
    for d in doctors:
        c = clinic_map.get(d["id"], {})
        d["clinic_name"] = c.get("clinic_name", "—")
        d["city"] = c.get("city", "—")
        d["consultation_fee"] = c.get("consultation_fee", "—")
    return {"doctors": doctors}


@router.get("/patients")
async def list_patients() -> dict:
    """Return all patients with basic info."""
    from app.database import db_fetch_many
    patients = await db_fetch_many("patients")
    return {"patients": patients}


@router.get("/appointments")
async def list_appointments() -> dict:
    """Return all appointments enriched with patient and doctor names."""
    from app.database import db_fetch_many
    # Sequential — sync Supabase client can't share HTTP/2 connection across parallel threads
    appts    = await db_fetch_many("appointments", order_by="-created_at")
    patients = await db_fetch_many("patients")
    doctors  = await db_fetch_many("doctors")
    patient_map = {p["id"]: p for p in patients}
    doctor_map  = {d["id"]: d for d in doctors}
    for a in appts:
        pt = patient_map.get(a.get("patient_id"), {})
        dr = doctor_map.get(a.get("doctor_id"), {})
        a["patient_name"] = pt.get("full_name") or pt.get("name") or "—"
        a["doctor_name"]  = dr.get("name") or "—"
    return {"appointments": appts}
