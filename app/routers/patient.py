"""Patient API endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_patient
from app.database import db_fetch_one, db_update, db_upsert
from app.schemas.patient import (
    PatientProfileRequest,
    LanguageRequest,
    SymptomsRequest,
    FollowupRequest,
    SelectDoctorRequest,
    SelectDateRequest,
    BookAppointmentRequest,
    CancelAppointmentRequest,
    BrowseSpecialtyRequest,
    PatientProfileResponse,
    SessionStateResponse,
    FollowupQuestionResponse,
    AvailableDateResponse,
    TimeWindowResponse,
    AppointmentResponse,
)
from app.services.llm_service import analyze_symptoms, LLMResult
from app.services.doctor_search import (
    find_doctors_for_multiple_specs,
    format_doctor_card,
    get_available_specializations,
)
from app.services.session_service import (
    get_or_create_session,
    update_session,
    open_analytics_session,
    close_analytics_session,
)
from app.services.appointment_service import (
    create_appointment,
    cancel_appointment,
    get_patient_appointments,
)
from app.services.notification_service import (
    create_notification,
    notify_doctor_new_appointment,
    notify_doctor_appointment_cancelled,
)
from app.utils.slot_utils import (
    get_available_dates,
    get_windows_for_date,
    build_available_slots_from_days_times,
)
from app.utils.messages import get_message
from app.utils.activity_logger import log_event
from app.constants import PatientState, SLOT_ID_TO_WINDOW, SPECIALIZATION_DISPLAY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/patient", tags=["patient"])


# ---------------------------------------------------------------------------
# Profile & Session
# ---------------------------------------------------------------------------

@router.get("/session", response_model=SessionStateResponse)
async def get_session(patient: dict = Depends(get_current_patient)) -> SessionStateResponse:
    """Return current session state and basic profile info."""
    session = await get_or_create_session(patient["whatsapp_number"])
    has_profile = bool(patient.get("name"))
    return SessionStateResponse(
        state=session["state"],
        has_profile=has_profile,
        language=patient.get("language"),
        context=session.get("context", {}),
    )


@router.post("/profile")
async def upsert_profile(
    body: PatientProfileRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Create or update patient profile. Language is NOT overwritten on update."""
    phone = patient["whatsapp_number"]
    is_new = not bool(patient.get("name"))

    update_data: dict = {}
    if body.resolved_name:
        update_data["name"] = body.resolved_name
    if body.age is not None:
        update_data["age"] = body.age
    if body.gender:
        update_data["gender"] = body.gender
    if body.state:
        update_data["state"] = body.state
    if body.city:
        update_data["city"] = body.city
    if body.pincode:
        update_data["pincode"] = body.pincode
    if body.language:
        update_data["language"] = body.language
    if not update_data:
        return {"message": "Nothing to update"}
    if is_new and "language" not in update_data:
        update_data["language"] = patient.get("language")

    await db_update("patients", {"id": patient["id"]}, update_data)

    session = await get_or_create_session(phone)
    ctx = session.get("context", {})
    await update_session(phone, PatientState.SHOWING_MENU, ctx)

    event = "patient_registered" if is_new else "patient_profile_updated"
    await log_event(
        event,
        role="patient",
        phone_number=phone,
        detail={"name": body.full_name, "city": body.city, "age": body.age},
    )
    return {"message": "Profile saved", "state": PatientState.SHOWING_MENU}


@router.get("/profile", response_model=PatientProfileResponse)
async def get_profile(patient: dict = Depends(get_current_patient)) -> PatientProfileResponse:
    return PatientProfileResponse(
        id=patient["id"],
        phone_number=patient["whatsapp_number"],
        name=patient.get("name", ""),
        age=patient.get("age", 0),
        gender=patient.get("gender", ""),
        state=patient.get("state"),
        city=patient.get("city", ""),
        pincode=patient.get("pincode", ""),
        language=patient.get("language"),
        registered_at=patient.get("registered_at", ""),
    )


@router.post("/language")
async def set_language(
    body: LanguageRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Set or update preferred language."""
    phone = patient["whatsapp_number"]
    await db_update("patients", {"id": patient["id"]}, {"language": body.language})

    session = await get_or_create_session(phone)
    ctx = session.get("context", {})
    ctx["preferred_language"] = body.language
    await update_session(phone, PatientState.SHOWING_MENU, ctx)

    return {
        "message": get_message("LANGUAGE_CHANGED", body.language),
        "language": body.language,
        "state": PatientState.SHOWING_MENU,
    }


@router.get("/menu")
async def get_menu(patient: dict = Depends(get_current_patient)) -> dict:
    """Return main menu options and current state."""
    if not patient.get("name"):
        return {
            "state": PatientState.AWAITING_PROFILE_FLOW,
            "message": get_message("WELCOME_NEW", patient.get("language") or "english"),
        }
    session = await get_or_create_session(patient["whatsapp_number"])
    lang = patient.get("language") or "english"
    name = patient["name"]
    return {
        "state": session["state"],
        "message": get_message("MENU_PROMPT", lang, name=name),
        "menu_options": [
            {"id": "book_appointment", "label": get_message("BTN_BOOK", lang)},
            {"id": "browse_doctors", "label": get_message("BTN_BROWSE_DOCTORS", lang)},
            {"id": "view_appointments", "label": get_message("BTN_VIEW", lang)},
            {"id": "update_profile", "label": get_message("BTN_UPDATE_PROFILE", lang)},
            {"id": "change_language", "label": get_message("BTN_CHANGE_LANGUAGE", lang)},
        ],
    }


# ---------------------------------------------------------------------------
# Symptom Analysis Flow
# ---------------------------------------------------------------------------

@router.post("/symptoms")
async def submit_symptoms(
    body: SymptomsRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """
    Start symptom analysis. Returns either a follow-up question or a list of doctors.
    Opens a new analytics session.
    """
    if not patient.get("name"):
        raise HTTPException(400, "Please complete your profile first")

    phone = patient["whatsapp_number"]
    lang = patient.get("language") or "english"
    session = await get_or_create_session(phone)
    ctx = session.get("context", {})

    # Close any existing analytics session
    if ctx.get("session_id"):
        await close_analytics_session(ctx["session_id"], session["state"], "new_booking", ctx)

    session_id = await open_analytics_session(phone, patient["id"])
    ctx = {
        "preferred_language": lang,
        "session_id": session_id,
        "symptoms": body.symptoms_text,
        "followup_turns": [],
        "excluded_doctor_ids": [],
    }
    await update_session(phone, PatientState.COLLECTING_SYMPTOMS, ctx)
    await log_event("symptoms_submitted", "patient", phone, {"symptoms": body.symptoms_text, "session_id": session_id})

    result = await analyze_symptoms(
        age=patient.get("age", 30),
        gender=patient.get("gender", "other"),
        symptoms_text=body.symptoms_text,
        followup_turns=[],
        language=lang,
    )

    await log_event(
        "llm_analysis_complete", "patient", phone,
        {"specializations": result.specializations, "urgency": result.urgency,
         "is_emergency": result.is_emergency, "has_followup": bool(result.followup_question),
         "session_id": session_id},
    )

    ctx["llm_result"] = _llm_result_to_dict(result)

    if result.followup_question:
        ctx["followup_turns"] = [{"role": "question", "content": result.followup_question}]
        await update_session(phone, PatientState.COLLECTING_FOLLOWUP, ctx)
        response = {
            "state": PatientState.COLLECTING_FOLLOWUP,
            "followup_question": result.followup_question,
            "is_emergency": result.is_emergency,
            "urgency": result.urgency,
        }
        if result.is_emergency:
            response["emergency_warning"] = get_message("EMERGENCY_WARNING", lang)
        return response

    # No follow-up — go straight to doctors
    return await _build_doctor_response(patient, ctx, result, phone, lang)


@router.post("/followup")
async def submit_followup(
    body: FollowupRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Answer a follow-up question from the LLM. Returns next question or doctors."""
    phone = patient["whatsapp_number"]
    lang = patient.get("language") or "english"
    session = await get_or_create_session(phone)

    if session["state"] != PatientState.COLLECTING_FOLLOWUP:
        raise HTTPException(400, f"Not in follow-up state (current: {session['state']})")

    ctx = session.get("context", {})
    turns: list[dict] = ctx.get("followup_turns", [])
    turns.append({"role": "answer", "content": body.answer})
    ctx["followup_turns"] = turns

    answered_turns = sum(1 for t in turns if t["role"] == "answer")
    settings_max = 13  # max followup turns
    force_conclude = answered_turns >= settings_max

    result = await analyze_symptoms(
        age=patient.get("age", 30),
        gender=patient.get("gender", "other"),
        symptoms_text=ctx.get("symptoms", ""),
        followup_turns=turns,
        language=lang,
        force_conclude=force_conclude,
    )

    ctx["llm_result"] = _llm_result_to_dict(result)

    if result.followup_question and not force_conclude:
        turns.append({"role": "question", "content": result.followup_question})
        ctx["followup_turns"] = turns
        await update_session(phone, PatientState.COLLECTING_FOLLOWUP, ctx)
        response = {
            "state": PatientState.COLLECTING_FOLLOWUP,
            "followup_question": result.followup_question,
            "is_emergency": result.is_emergency,
            "urgency": result.urgency,
        }
        if result.is_emergency:
            response["emergency_warning"] = get_message("EMERGENCY_WARNING", lang)
        return response

    # Concluded — find doctors
    return await _build_doctor_response(patient, ctx, result, phone, lang)


# ---------------------------------------------------------------------------
# Doctor Discovery
# ---------------------------------------------------------------------------

@router.post("/select-doctor")
async def select_doctor(
    body: SelectDoctorRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Select a doctor and get available dates in the next 7 days."""
    phone = patient["whatsapp_number"]
    session = await get_or_create_session(phone)
    ctx = session.get("context", {})

    doctor = await db_fetch_one("doctors", {"id": body.doctor_id})
    if not doctor:
        raise HTTPException(404, "Doctor not found")

    # Get first active clinic's slots (or merge all)
    clinics_rows = await _get_doctor_clinics(body.doctor_id)
    all_slots = []
    for c in clinics_rows:
        all_slots.extend(c.get("available_slots", []))

    rejected_windows = ctx.get("rejected_slots", {})
    dates = get_available_dates(all_slots, rejected_windows=rejected_windows, doctor_id=body.doctor_id)

    lang = patient.get("language") or "english"

    if not dates:
        return {
            "state": PatientState.SHOWING_DOCTORS,
            "message": get_message("NO_SLOTS_THIS_WEEK", lang, name=doctor["name"]),
            "available_dates": [],
            "doctor": {"id": doctor["id"], "name": doctor["name"]},
        }

    ctx["selected_doctor_id"] = body.doctor_id
    clinic_id = clinics_rows[0]["id"] if clinics_rows else None
    ctx["selected_clinic_id"] = clinic_id
    await update_session(phone, PatientState.AWAITING_SLOT_FLOW, ctx)

    return {
        "state": PatientState.AWAITING_SLOT_FLOW,
        "message": get_message("PICK_A_DAY", lang, name=doctor["name"]),
        "doctor": {"id": doctor["id"], "name": doctor["name"]},
        "available_dates": dates,
    }


@router.post("/select-date")
async def select_date(
    body: SelectDateRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Select a date and get available time windows."""
    phone = patient["whatsapp_number"]
    session = await get_or_create_session(phone)
    ctx = session.get("context", {})
    lang = patient.get("language") or "english"

    clinics_rows = await _get_doctor_clinics(body.doctor_id)
    all_slots = []
    for c in clinics_rows:
        all_slots.extend(c.get("available_slots", []))

    rejected_slots = ctx.get("rejected_slots", {})
    rejected_window = rejected_slots.get(body.doctor_id)

    windows = get_windows_for_date(all_slots, body.date, rejected_window=rejected_window)

    ctx["pending_slot_date"] = body.date
    ctx["selected_doctor_id"] = body.doctor_id
    await update_session(phone, PatientState.AWAITING_SLOT_TIME, ctx)

    return {
        "state": PatientState.AWAITING_SLOT_TIME,
        "message": get_message("PICK_A_TIME", lang, date=body.date),
        "date": body.date,
        "windows": [
            TimeWindowResponse(
                slot_id=w,
                label=_window_label(w),
                window=SLOT_ID_TO_WINDOW[w],
            )
            for w in windows
        ],
    }


@router.post("/book")
async def book_appointment(
    body: BookAppointmentRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Book an appointment with a doctor."""
    phone = patient["whatsapp_number"]
    lang = patient.get("language") or "english"
    session = await get_or_create_session(phone)
    ctx = session.get("context", {})

    llm_result_dict = ctx.get("llm_result", {})
    symptoms_summary = llm_result_dict.get("summary")
    urgency = llm_result_dict.get("urgency", "routine")

    try:
        appt = await create_appointment(
            patient_id=patient["id"],
            doctor_id=body.doctor_id,
            slot_day=body.slot_day,
            slot_window=body.slot_window,
            clinic_id=body.clinic_id or ctx.get("selected_clinic_id"),
            symptoms_summary=symptoms_summary,
            urgency=urgency,
        )
    except ValueError as e:
        err = str(e)
        if err.startswith("duplicate:"):
            _, doc_name, slot_day = err.split(":", 2)
            return {
                "state": PatientState.AWAITING_SLOT_FLOW,
                "error": "duplicate_booking",
                "message": get_message("DUPLICATE_BOOKING", lang, name=doc_name, slot_day=slot_day),
            }
        raise HTTPException(400, str(e))

    ctx["appointment_id"] = appt["id"]
    ctx["wait_replied"] = False
    ctx["cancel_confirm_pending"] = False
    await update_session(phone, PatientState.CONFIRMING, ctx)

    # Notify doctor
    doctor = await db_fetch_one("doctors", {"id": body.doctor_id})
    if doctor:
        await notify_doctor_new_appointment(
            doctor_id=doctor["id"],
            doctor_name=doctor["name"],
            doctor_phone=doctor["whatsapp_number"],
            appointment_id=appt["id"],
            patient_name=patient["name"],
            patient_age=patient.get("age", 0),
            patient_gender=patient.get("gender", ""),
            symptoms_summary=symptoms_summary,
            urgency=urgency,
            slot_day=body.slot_day,
            slot_window=body.slot_window,
        )

    # In-app notification for doctor
    if doctor:
        await create_notification(
            recipient_role="doctor",
            recipient_id=doctor["id"],
            type="new_appointment",
            title="New Appointment Request",
            body=f"{patient['name']} wants to book {body.slot_day} ({body.slot_window}). Urgency: {urgency}.",
            metadata={"appointment_id": appt["id"], "patient_id": patient["id"]},
        )

    await log_event(
        "appointment_created", "patient", phone,
        {"appointment_id": appt["id"], "doctor_id": body.doctor_id,
         "slot_day": body.slot_day, "slot_window": body.slot_window,
         "urgency": urgency, "session_id": ctx.get("session_id")},
    )

    doctor_name = doctor["name"] if doctor else "the doctor"
    return {
        "state": PatientState.CONFIRMING,
        "appointment_id": appt["id"],
        "message": get_message("APPOINTMENT_PENDING", lang, name=doctor_name),
    }


@router.post("/cancel")
async def cancel_patient_appointment(
    body: CancelAppointmentRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Cancel an appointment."""
    phone = patient["whatsapp_number"]
    lang = patient.get("language") or "english"

    appt = await db_fetch_one("appointments", {"id": body.appointment_id})
    if not appt or appt["patient_id"] != patient["id"]:
        raise HTTPException(404, "Appointment not found")

    await cancel_appointment(body.appointment_id)

    # Notify doctor
    doctor = await db_fetch_one("doctors", {"id": appt["doctor_id"]})
    if doctor:
        await notify_doctor_appointment_cancelled(
            doctor["whatsapp_number"], patient["name"]
        )

    session = await get_or_create_session(phone)
    ctx = session.get("context", {})
    await update_session(phone, PatientState.SHOWING_MENU, ctx)

    return {
        "state": PatientState.SHOWING_MENU,
        "message": get_message("APPOINTMENT_CANCELLED_PATIENT", lang),
    }


@router.get("/appointments")
async def get_appointments(patient: dict = Depends(get_current_patient)) -> dict:
    """Return recent patient appointments (last 10, active first)."""
    appts = await get_patient_appointments(patient["id"])
    lang = patient.get("language") or "english"

    if not appts:
        return {
            "appointments": [],
            "message": get_message("NO_APPOINTMENTS", lang),
        }

    return {
        "appointments": [
            {
                "id": a["id"],
                "doctor_name": a.get("doctor_name", ""),
                "doctor_id": a.get("doctor_id", ""),
                "specialization": a.get("doctor_specialization", ""),
                "clinic_name": a.get("clinic_name", ""),
                "slot_day": a.get("slot_day", ""),
                "slot_window": a.get("slot_window", ""),
                "appointment_time": a.get("appointment_time"),
                "symptoms_summary": a.get("symptoms_summary"),
                "urgency": a.get("urgency", "medium"),
                "status": a.get("status", "pending"),
                "created_at": a.get("created_at", ""),
            }
            for a in appts
        ]
    }


# ---------------------------------------------------------------------------
# Browse Specialties
# ---------------------------------------------------------------------------

@router.get("/specialties")
async def get_specialties(patient: dict = Depends(get_current_patient)) -> dict:
    """Return available specializations near the patient."""
    lang = patient.get("language") or "english"
    specialties = await get_available_specializations(
        patient.get("pincode", ""), patient.get("city", "")
    )
    if not specialties:
        return {
            "specialties": [],
            "message": get_message("NO_SPECIALTIES_AVAILABLE", lang),
        }
    return {
        "specialties": specialties,
        "message": get_message("BROWSE_SPECIALTY_PROMPT", lang),
    }


@router.post("/browse-specialty")
async def browse_specialty(
    body: BrowseSpecialtyRequest, patient: dict = Depends(get_current_patient)
) -> dict:
    """Browse doctors by specialty (without symptom analysis)."""
    phone = patient["whatsapp_number"]
    lang = patient.get("language") or "english"
    session = await get_or_create_session(phone)
    ctx = session.get("context", {})

    # Close existing session
    if ctx.get("session_id"):
        await close_analytics_session(ctx["session_id"], session["state"], "new_booking", ctx)

    session_id = await open_analytics_session(phone, patient["id"])
    spec = body.specialization.lower()
    ctx = {
        "preferred_language": lang,
        "session_id": session_id,
        "browse_specialty": spec,
        "excluded_doctor_ids": [],
        "llm_result": {
            "specializations": [spec],
            "display_names": [SPECIALIZATION_DISPLAY.get(spec, spec.title())],
            "summary": None,
            "urgency": "routine",
            "is_emergency": False,
        },
    }
    await update_session(phone, PatientState.BROWSING_SPECIALTY, ctx)

    fake_result = LLMResult(
        specializations=[spec],
        display_names=[SPECIALIZATION_DISPLAY.get(spec, spec.title())],
        summary=None,
        urgency="routine",
        is_emergency=False,
    )
    await log_event("browse_specialty_selected", "patient", phone, {"specialization": spec, "session_id": session_id})

    return await _build_doctor_response(patient, ctx, fake_result, phone, lang, is_browse=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _build_doctor_response(
    patient: dict,
    ctx: dict,
    result: LLMResult,
    phone: str,
    lang: str,
    is_browse: bool = False,
) -> dict:
    """Find doctors and build the response dict."""
    excluded = ctx.get("excluded_doctor_ids", [])
    doctors_raw, fallback_levels, fallback_spec = await find_doctors_for_multiple_specs(
        specializations=result.specializations,
        patient_pincode=patient.get("pincode", ""),
        patient_city=patient.get("city", ""),
        exclude_ids=excluded,
    )

    if not doctors_raw:
        spec_display = ", ".join(result.display_names)
        await log_event("no_doctors_found", "patient", phone, {"specializations": result.specializations, "session_id": ctx.get("session_id")})
        return {
            "state": PatientState.SHOWING_MENU,
            "doctors": [],
            "message": get_message("NO_DOCTORS_FOUND", lang, specialization=spec_display),
        }

    doctors_formatted = [format_doctor_card(d) for d in doctors_raw]
    doctor_ids = [d["id"] for d in doctors_formatted]
    ctx["doctors_shown"] = doctor_ids
    await update_session(phone, PatientState.SHOWING_DOCTORS, ctx)
    await log_event("doctors_shown", "patient", phone, {"count": len(doctor_ids), "doctor_ids": doctor_ids, "session_id": ctx.get("session_id")})

    # Build recommendation message
    spec_display = " / ".join(result.display_names)
    messages = []
    if not is_browse and result.summary is not None:
        if result.was_force_concluded:
            messages.append(get_message("SPECIALIST_RECOMMENDATION_UNCERTAIN", lang, specialties=spec_display))
        else:
            messages.append(get_message("SPECIALIST_RECOMMENDATION", lang, specialties=spec_display))

    if fallback_spec:
        messages.append(get_message("NO_DOCTORS_LOCAL", lang, specialization=fallback_spec.title()))
    else:
        messages.append(get_message("DOCTORS_LIST_BODY", lang))

    if result.is_emergency:
        messages.insert(0, get_message("EMERGENCY_WARNING", lang))

    return {
        "state": PatientState.SHOWING_DOCTORS,
        "messages": messages,
        "doctors": doctors_formatted,
        "is_emergency": result.is_emergency,
        "urgency": result.urgency,
    }


async def _get_doctor_clinics(doctor_id: str) -> list[dict]:
    from app.database import get_supabase
    import asyncio
    client = get_supabase()

    def _fetch():
        return (
            client.table("clinics")
            .select("*")
            .eq("doctor_id", doctor_id)
            .eq("is_active", True)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    return result.data or []


def _window_label(slot_id: str) -> str:
    labels = {
        "morning": "Morning (9–1 PM)",
        "afternoon": "Afternoon (1–5 PM)",
        "evening": "Evening (5–9 PM)",
    }
    return labels.get(slot_id, slot_id)


def _llm_result_to_dict(result: LLMResult) -> dict:
    return {
        "specializations": result.specializations,
        "display_names": result.display_names,
        "confidence_scores": result.confidence_scores,
        "summary": result.summary,
        "urgency": result.urgency,
        "is_emergency": result.is_emergency,
        "followup_question": result.followup_question,
        "has_followup": bool(result.followup_question),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/notifications")
async def get_patient_notifications(patient: dict = Depends(get_current_patient)) -> list:
    """Fetch unread + recent notifications for this patient."""
    from app.database import db_fetch_many
    return await db_fetch_many(
        "notifications",
        filters={"recipient_role": "patient", "recipient_id": patient["id"]},
        order_by="-created_at",
        limit=20,
    )


@router.post("/notifications/mark-read")
async def mark_patient_notifications_read(patient: dict = Depends(get_current_patient)) -> dict:
    """Mark all unread notifications as read for this patient."""
    from app.database import db_update_where
    await db_update_where(
        "notifications",
        {"recipient_role": "patient", "recipient_id": patient["id"], "is_read": False},
        {"is_read": True},
    )
    return {"message": "Marked as read"}
