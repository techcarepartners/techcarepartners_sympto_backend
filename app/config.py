from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "doctor-photos"

    # LLM
    gemini_api_key: str = ""

    # Auth
    jwt_secret: str = "change-me-in-production-32-chars-min"
    jwt_expiry_hours: int = 24

    # Internal / Admin
    internal_secret: str = "change-me-internal-secret"

    # Notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Sympto <noreply@sympto.in>"

    sms_api_key: str = ""

    # App
    port: int = 8000
    environment: str = "dev"
    frontend_url: str = "http://localhost:3000"

    # Session timeout (hours)
    session_timeout_hours: int = 3

    # LLM
    max_followup_turns: int = 13

    # Doctor placeholder photo
    doctor_placeholder_photo: str = (
        "https://mckhpzxslescidjbqpxp.supabase.co/storage/v1/object/public/"
        "doctor-photos/placeholder.jpeg"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
