"""Doctor discovery with 3-level fallback search."""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.database import get_supabase
from app.constants import MAX_DOCTORS_PER_CAROUSEL
from app.utils.slot_utils import build_availability_string, get_available_dates

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _is_on_vacation(doctor: dict) -> bool:
    now = datetime.now(IST)
    start = doctor.get("vacation_start")
    end = doctor.get("vacation_end")
    if not start or not end:
        return False
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(IST)
        e = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(IST)
        return s <= now <= e
    except Exception:
        return False


async def _query_doctors(
    specialization: str,
    pincode: str | None = None,
    city: str | None = None,
    exclude_ids: list[str] | None = None,
    limit: int = MAX_DOCTORS_PER_CAROUSEL,
) -> list[dict]:
    """Raw doctor + clinic query from Supabase."""
    client = get_supabase()
    exclude_ids = exclude_ids or []

    def _fetch():
        # Join doctors with their active clinics
        q = (
            client.table("doctors")
            .select("*, clinics!inner(*)")
            .eq("is_approved", True)
            .eq("clinics.is_active", True)
            .eq("specialization", specialization)
            .order("is_member", desc=True)
            .order("registered_at", desc=False)
            .limit(limit * 3)  # fetch extra to account for vacation/dedup filtering
        )
        if pincode:
            q = q.eq("clinics.pincode", pincode)
        if city:
            q = q.eq("clinics.city", city)
        return q.execute()

    result = await asyncio.to_thread(_fetch)
    rows = result.data or []

    # Filter: exclude IDs, vacation, must have future availability
    seen_ids: set[str] = set()
    filtered = []
    for row in rows:
        doc_id = row["id"]
        if doc_id in exclude_ids or doc_id in seen_ids:
            continue
        if _is_on_vacation(row):
            continue
        clinics = row.get("clinics", [])
        if not isinstance(clinics, list):
            clinics = [clinics]
        # Check at least one active clinic has future availability
        has_future = False
        for clinic in clinics:
            slots = clinic.get("available_slots", [])
            dates = get_available_dates(slots)
            if dates:
                has_future = True
                break
        if not has_future:
            continue
        seen_ids.add(doc_id)
        filtered.append(row)
        if len(filtered) >= limit:
            break

    return filtered


async def find_doctors_for_specialization(
    specialization: str,
    patient_pincode: str,
    patient_city: str,
    exclude_ids: list[str] | None = None,
) -> tuple[list[dict], str]:
    """
    3-level fallback search for doctors.
    Returns (doctors, fallback_level) where fallback_level is 'pincode' | 'city' | 'all'.
    """
    exclude_ids = exclude_ids or []

    # Level 1: By pincode
    doctors = await _query_doctors(specialization, pincode=patient_pincode, exclude_ids=exclude_ids)
    if doctors:
        return doctors, "pincode"

    # Level 2: By city
    doctors = await _query_doctors(specialization, city=patient_city, exclude_ids=exclude_ids)
    if doctors:
        return doctors, "city"

    # Level 3: All India
    doctors = await _query_doctors(specialization, exclude_ids=exclude_ids)
    return doctors, "all"


async def find_doctors_for_multiple_specs(
    specializations: list[str],
    patient_pincode: str,
    patient_city: str,
    exclude_ids: list[str] | None = None,
) -> tuple[list[dict], dict[str, str], str | None]:
    """
    Find doctors for one or more specializations.
    Returns (doctors, fallback_levels_by_spec, fallback_message).
    Deduplicates — a doctor only appears once.
    """
    exclude_ids = exclude_ids or []
    seen_ids: set[str] = set()
    all_doctors: list[dict] = []
    fallback_levels: dict[str, str] = {}
    fallback_message = None

    for spec in specializations:
        doctors, level = await find_doctors_for_specialization(
            spec, patient_pincode, patient_city, exclude_ids=list(set(exclude_ids) | seen_ids)
        )
        fallback_levels[spec] = level
        if level == "all" and not fallback_message:
            fallback_message = spec

        for doc in doctors:
            if doc["id"] not in seen_ids:
                seen_ids.add(doc["id"])
                all_doctors.append(doc)

    return all_doctors, fallback_levels, fallback_message


def format_doctor_card(doctor: dict) -> dict:
    """Format a raw doctor DB row into a clean doctor card dict."""
    clinics = doctor.get("clinics", [])
    if not isinstance(clinics, list):
        clinics = [clinics]
    active_clinics = [c for c in clinics if c.get("is_active")]

    # Use first active clinic for display
    primary_clinic = active_clinics[0] if active_clinics else {}
    all_slots = []
    for c in active_clinics:
        all_slots.extend(c.get("available_slots", []))

    return {
        "id": doctor["id"],
        "name": f"Dr. {doctor['name']}",
        "specialization": doctor["specialization"].title(),
        "clinic_name": primary_clinic.get("clinic_name", ""),
        "city": primary_clinic.get("city", "").title(),
        "availability_string": build_availability_string(all_slots),
        "photo_url": doctor.get("photo_url"),
        "is_member": doctor.get("is_member", False),
        "clinics": [
            {
                "id": c["id"],
                "clinic_name": c["clinic_name"],
                "city": c["city"],
                "state": c["state"],
                "pincode": c["pincode"],
                "address": c.get("address", ""),
                "maps": c.get("maps", ""),
                "available_slots": c.get("available_slots", []),
            }
            for c in active_clinics
        ],
    }


async def get_available_specializations(patient_pincode: str, patient_city: str) -> list[dict]:
    """
    Return all distinct specializations with at least one bookable doctor
    near the patient's location.
    """
    from app.constants import VALID_SPECIALIZATIONS, SPECIALIZATION_DISPLAY
    client = get_supabase()

    def _fetch():
        return (
            client.table("doctors")
            .select("specialization, clinics!inner(pincode, city, available_slots, is_active)")
            .eq("is_approved", True)
            .eq("clinics.is_active", True)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    rows = result.data or []

    counts: dict[str, int] = {}
    for row in rows:
        spec = row["specialization"]
        if not _is_on_vacation(row):
            counts[spec] = counts.get(spec, 0) + 1

    return [
        {
            "specialization": spec,
            "display_name": SPECIALIZATION_DISPLAY.get(spec, spec.title()),
            "doctor_count": count,
        }
        for spec, count in sorted(counts.items())
        if count > 0
    ]
