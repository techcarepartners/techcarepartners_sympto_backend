"""Authentication — phone number based JWT issuance."""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException

from jose import jwt

from app.config import get_settings
from app.database import db_fetch_one, db_upsert
from app.schemas.auth import PatientLoginRequest, DoctorLoginRequest, TokenResponse
from app.utils.activity_logger import log_event

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _normalize_phone(raw: str) -> str:
    """Strip spaces, dashes, and leading +.
    Tries to return a consistent format for DB lookup.
    Also falls back to trying with/without country-code prefix."""
    p = raw.strip().replace(" ", "").replace("-", "").replace("+", "")
    return p


async def _find_doctor(phone: str) -> dict | None:
    """Try multiple phone formats to find the doctor."""
    # Exact match first
    row = await db_fetch_one("doctors", {"whatsapp_number": phone})
    if row:
        return row
    # Try with leading + (some entries may be stored as +91...)
    row = await db_fetch_one("doctors", {"whatsapp_number": "+" + phone})
    if row:
        return row
    # If 12-digit (91XXXXXXXXXX), also try 10-digit (drop country code)
    if len(phone) == 12 and phone.startswith("91"):
        row = await db_fetch_one("doctors", {"whatsapp_number": phone[2:]})
        if row:
            return row
    # If 10-digit, also try with 91 prefix
    if len(phone) == 10:
        row = await db_fetch_one("doctors", {"whatsapp_number": "91" + phone})
        if row:
            return row
    return None


async def _find_patient(phone: str) -> dict | None:
    """Try multiple phone formats to find the patient."""
    row = await db_fetch_one("patients", {"whatsapp_number": phone})
    if row:
        return row
    row = await db_fetch_one("patients", {"whatsapp_number": "+" + phone})
    if row:
        return row
    if len(phone) == 12 and phone.startswith("91"):
        row = await db_fetch_one("patients", {"whatsapp_number": phone[2:]})
        if row:
            return row
    if len(phone) == 10:
        row = await db_fetch_one("patients", {"whatsapp_number": "91" + phone})
        if row:
            return row
    return None


def _create_token(subject_id: str, role: str) -> str:
    settings = get_settings()
    payload = {
        "sub": subject_id,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@router.post("/patient/login", response_model=TokenResponse)
async def patient_login(body: PatientLoginRequest) -> TokenResponse:
    """
    Register or log in a patient by phone number.
    Returns a JWT and whether this is a new user.
    """
    phone = _normalize_phone(body.phone_number)
    existing = await _find_patient(phone)

    is_new = existing is None
    has_profile = not is_new

    if is_new:
        # Create a minimal placeholder patient record (profile filled later)
        row = await db_upsert(
            "patients",
            {
                "whatsapp_number": phone,
                "name": "",
                "age": 0,
                "gender": "other",
                "city": "",
                "pincode": "000000",
                "language": body.language,
            },
            on_conflict="whatsapp_number",
        )
        patient_id = row["id"]
        await log_event("new_user_first_contact", role="patient", phone_number=phone)
    else:
        patient_id = existing["id"]
        # Only set language if not already set
        if body.language and not existing.get("language"):
            from app.database import db_update
            await db_update("patients", {"id": patient_id}, {"language": body.language})

    token = _create_token(patient_id, "patient")
    return TokenResponse(
        access_token=token,
        role="patient",
        is_new_user=is_new,
        has_profile=has_profile and bool(existing.get("name") if existing else False),
    )


@router.post("/doctor/login", response_model=TokenResponse)
async def doctor_login(body: DoctorLoginRequest) -> TokenResponse:
    """
    Register or log in a doctor by phone number.
    A new doctor account is created if none exists; profile is filled via /api/doctor/register.
    """
    phone = _normalize_phone(body.phone_number)
    existing = await _find_doctor(phone)

    is_new = existing is None
    has_profile = not is_new

    if is_new:
        row = await db_upsert(
            "doctors",
            {
                "whatsapp_number": phone,
                "name": "",
                "specialization": "",
                "is_approved": False,
                "is_member": False,
                "multi_clinic": False,
            },
            on_conflict="whatsapp_number",
        )
        doctor_id = row["id"]
    else:
        doctor_id = existing["id"]
        has_profile = bool(existing.get("name"))

    token = _create_token(doctor_id, "doctor")
    return TokenResponse(
        access_token=token,
        role="doctor",
        is_new_user=is_new,
        has_profile=has_profile,
    )
