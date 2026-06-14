from typing import Final

# ---------------------------------------------------------------------------
# Specializations
# ---------------------------------------------------------------------------

VALID_SPECIALIZATIONS: Final[set[str]] = {
    "cardiologist",
    "dermatologist",
    "ent",
    "general physician",
    "gynaecologist",
    "neurologist",
    "ophthalmologist",
    "orthopaedic",
    "paediatrician",
    "psychiatrist",
    "urologist",
    "other",
}

# Display names for LLM (title-case)
SPECIALIZATION_DISPLAY: Final[dict[str, str]] = {
    "cardiologist": "Cardiologist",
    "dermatologist": "Dermatologist",
    "ent": "ENT",
    "general physician": "General Physician",
    "gynaecologist": "Gynaecologist",
    "neurologist": "Neurologist",
    "ophthalmologist": "Ophthalmologist",
    "orthopaedic": "Orthopaedic",
    "paediatrician": "Paediatrician",
    "psychiatrist": "Psychiatrist",
    "urologist": "Urologist",
    "other": "Other",
}

# ---------------------------------------------------------------------------
# Slot / window mappings
# ---------------------------------------------------------------------------

# DB available_slots window values (lowercase) → display
WINDOW_DISPLAY: Final[dict[str, str]] = {
    "9am - 1pm": "Morning (9–1 PM)",
    "1pm - 5pm": "Afternoon (1–5 PM)",
    "5pm - 9pm": "Evening (5–9 PM)",
}

# Slot ID → normalized DB window for appointments table (title-case)
SLOT_ID_TO_WINDOW: Final[dict[str, str]] = {
    "morning": "9AM - 1PM",
    "afternoon": "1PM - 5PM",
    "evening": "5PM - 9PM",
}

# available_slots window (lowercase) → slot_id
WINDOW_TO_SLOT_ID: Final[dict[str, str]] = {
    "9am - 1pm": "morning",
    "1pm - 5pm": "afternoon",
    "5pm - 9pm": "evening",
}

# Slot ordering for sorting
SLOT_ORDER: Final[dict[str, int]] = {
    "morning": 0,
    "afternoon": 1,
    "evening": 2,
}

# Day abbreviation → full lowercase name
DAY_ABBR_TO_FULL: Final[dict[str, str]] = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
}

# Full lowercase → weekday index (Mon=0)
DAY_TO_INDEX: Final[dict[str, int]] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# Day abbreviation for display (for doctor cards)
DAY_SHORT: Final[dict[str, str]] = {
    "monday": "Mo",
    "tuesday": "Tu",
    "wednesday": "We",
    "thursday": "Th",
    "friday": "Fr",
    "saturday": "Sa",
    "sunday": "Su",
}

# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------

APPOINTMENT_STATUSES: Final[set[str]] = {"pending", "confirmed", "cancelled"}
URGENCY_LEVELS: Final[set[str]] = {"routine", "urgent", "emergency"}

# ---------------------------------------------------------------------------
# Patient states
# ---------------------------------------------------------------------------

class PatientState:
    IDLE = "IDLE"
    AWAITING_LANGUAGE = "AWAITING_LANGUAGE"
    AWAITING_PROFILE_FLOW = "AWAITING_PROFILE_FLOW"
    SHOWING_MENU = "SHOWING_MENU"
    COLLECTING_SYMPTOMS = "COLLECTING_SYMPTOMS"
    COLLECTING_FOLLOWUP = "COLLECTING_FOLLOWUP"
    SHOWING_DOCTORS = "SHOWING_DOCTORS"
    AWAITING_SLOT_FLOW = "AWAITING_SLOT_FLOW"
    AWAITING_SLOT_TIME = "AWAITING_SLOT_TIME"
    CONFIRMING = "CONFIRMING"
    REJECTION_CHOICE = "REJECTION_CHOICE"
    VIEWING_APPOINTMENTS = "VIEWING_APPOINTMENTS"
    CANCELLING_APPOINTMENT = "CANCELLING_APPOINTMENT"
    BROWSING_SPECIALTY = "BROWSING_SPECIALTY"


# ---------------------------------------------------------------------------
# Doctor states
# ---------------------------------------------------------------------------

class DoctorState:
    IDLE = "IDLE"
    AWAITING_REGISTRATION_FLOW = "AWAITING_REGISTRATION_FLOW"


# ---------------------------------------------------------------------------
# Supported languages
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES: Final[set[str]] = {"english", "hindi", "hinglish"}

# ---------------------------------------------------------------------------
# Max doctors per search result page
# ---------------------------------------------------------------------------

MAX_DOCTORS_PER_CAROUSEL: Final[int] = 5
MAX_SPECIALTIES_PER_PAGE: Final[int] = 8

# ---------------------------------------------------------------------------
# LLM model fallback chain
# ---------------------------------------------------------------------------

LLM_MODEL_CHAIN: Final[list[str]] = [
    "gemini/gemini-2.5-flash-lite",
    "gemini/gemini-2.5-flash",
    "gemini/gemini-1.5-flash",
]
