from pydantic import BaseModel, Field, field_validator
from typing import Literal


class DoctorRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: str | None = None
    registration_number: str | None = None
    year_register: str | None = None
    specialization: str
    clinic_name: str
    address: str = ""
    state: str
    city: str
    pincode: str = Field(..., min_length=6, max_length=6)
    maps: str = ""
    available_days: list[str] = Field(..., description="List of day abbreviations: Mon, Tue, etc.")
    time_slots: list[str] = Field(..., description="List of slot IDs: morning, afternoon, evening")

    @field_validator("specialization", mode="before")
    @classmethod
    def lower_spec(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("state", "city", "clinic_name", mode="before")
    @classmethod
    def lower_text(cls, v: str) -> str:
        return v.strip().lower()


class DoctorUpdateProfileRequest(BaseModel):
    name: str | None = None
    specialization: str | None = None


class ClinicRequest(BaseModel):
    clinic_name: str
    address: str = ""
    state: str
    city: str
    pincode: str = Field(..., min_length=6, max_length=6)
    maps: str = ""
    # New granular format: [{day, start, end}] — takes priority over available_days/time_slots
    schedule: list[dict] = Field(default_factory=list, description="[{day, start, end}] per-day time ranges")
    # Legacy flat format (still accepted for backward compat)
    available_days: list[str] = Field(default_factory=list)
    time_slots: list[str] = Field(default_factory=list)


class UpdateAvailabilityRequest(BaseModel):
    available_days: list[str]
    time_slots: list[str]
    clinic_id: str | None = None
    update_all: bool = False


class VacationRequest(BaseModel):
    vacation_start: str = Field(..., description="ISO date YYYY-MM-DD")
    vacation_end: str = Field(..., description="ISO date YYYY-MM-DD")
    vacation_reason: str | None = Field(None, description="Reason shown on calendar hover")


class VacationCreateRequest(BaseModel):
    vacation_start: str = Field(..., description="ISO date YYYY-MM-DD")
    vacation_end: str = Field(..., description="ISO date YYYY-MM-DD")
    vacation_reason: str = Field("On Vacation", description="Reason shown on calendar hover")


class VacationUpdateRequest(BaseModel):
    vacation_start: str | None = Field(None, description="ISO date YYYY-MM-DD")
    vacation_end: str | None = Field(None, description="ISO date YYYY-MM-DD")
    vacation_reason: str | None = Field(None, description="Reason shown on calendar hover")


class AppointmentActionRequest(BaseModel):
    appointment_id: str
    appointment_time: str | None = None   # ISO8601, optional for confirm


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ClinicResponse(BaseModel):
    id: str
    clinic_name: str
    city: str
    state: str
    pincode: str
    address: str
    maps: str
    available_slots: list[dict]
    is_active: bool


class DoctorProfileResponse(BaseModel):
    id: str
    phone_number: str
    name: str
    email: str | None
    registration_number: str | None
    year_register: str | None
    specialization: str
    photo_url: str | None
    is_approved: bool
    is_member: bool
    multi_clinic: bool
    vacation_start: str | None
    vacation_end: str | None
    vacation_reason: str | None
    registered_at: str
    clinics: list[ClinicResponse]


class DoctorAppointmentResponse(BaseModel):
    id: str
    patient_name: str
    patient_id: str
    patient_age: int
    patient_gender: str
    slot_day: str
    slot_window: str
    appointment_time: str | None
    symptoms_summary: str | None
    urgency: str
    status: str
    created_at: str
