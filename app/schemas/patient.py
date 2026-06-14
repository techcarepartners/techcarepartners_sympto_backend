from pydantic import BaseModel, Field, field_validator
from typing import Literal, Any


class PatientProfileRequest(BaseModel):
    # Accept either 'full_name' (WhatsApp flow) or 'name' (web profile page)
    full_name: str | None = Field(None, min_length=1)
    name: str | None = Field(None, min_length=1)
    age: int | None = Field(None, ge=0, le=120)
    gender: str | None = None
    state: str | None = None
    city: str | None = None
    pincode: str | None = None
    language: str | None = None

    @property
    def resolved_name(self) -> str | None:
        return (self.full_name or self.name or "").strip() or None

    @field_validator("gender", mode="before")
    @classmethod
    def lower_gender(cls, v: str | None) -> str | None:
        return v.lower() if v else v

    @field_validator("state", "city", mode="before")
    @classmethod
    def lower_location(cls, v: str | None) -> str | None:
        return v.strip().lower() if v else v


class LanguageRequest(BaseModel):
    language: Literal["english", "hindi", "hinglish"]


class SymptomsRequest(BaseModel):
    symptoms_text: str = Field(..., min_length=3, description="Patient's symptom description")


class FollowupRequest(BaseModel):
    answer: str = Field(..., min_length=1, description="Patient's answer to the follow-up question")


class SelectDoctorRequest(BaseModel):
    doctor_id: str


class SelectDateRequest(BaseModel):
    doctor_id: str
    date: str = Field(..., description="ISO date string YYYY-MM-DD")


class BookAppointmentRequest(BaseModel):
    doctor_id: str
    slot_day: str = Field(..., description="Full day name, e.g. 'Monday'")
    slot_window: str = Field(..., description="Slot window, e.g. '9AM - 1PM'")
    clinic_id: str | None = None


class CancelAppointmentRequest(BaseModel):
    appointment_id: str


class BrowseSpecialtyRequest(BaseModel):
    specialization: str


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PatientProfileResponse(BaseModel):
    id: str
    phone_number: str
    name: str
    age: int
    gender: str
    state: str | None
    city: str
    pincode: str
    language: str | None
    registered_at: str


class SessionStateResponse(BaseModel):
    state: str
    has_profile: bool
    language: str | None
    context: dict[str, Any] = {}


class FollowupQuestionResponse(BaseModel):
    followup_question: str | None
    is_emergency: bool = False
    urgency: str = "routine"
    doctors: list[dict] | None = None
    message: str | None = None


class DoctorCardResponse(BaseModel):
    id: str
    name: str
    specialization: str
    clinic_name: str
    city: str
    availability_string: str
    photo_url: str | None
    is_member: bool


class AvailableDateResponse(BaseModel):
    date: str
    display: str
    weekday: str
    windows: list[str]
    windows_display: list[str]


class TimeWindowResponse(BaseModel):
    slot_id: str
    label: str
    window: str


class AppointmentResponse(BaseModel):
    id: str
    doctor_name: str
    doctor_id: str
    clinic_name: str | None
    slot_day: str
    slot_window: str
    appointment_time: str | None
    symptoms_summary: str | None
    urgency: str
    status: str
    created_at: str


class SpecialtyResponse(BaseModel):
    specialization: str
    display_name: str
    doctor_count: int
