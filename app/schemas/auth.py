from pydantic import BaseModel, Field


class PatientLoginRequest(BaseModel):
    phone_number: str = Field(..., description="Patient's phone number (E.164 or local)")
    language: str | None = Field(None, description="Preferred language: english | hindi | hinglish")


class DoctorLoginRequest(BaseModel):
    phone_number: str = Field(..., description="Doctor's phone number")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    is_new_user: bool
    has_profile: bool = True
