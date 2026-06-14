from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timezone

from app.config import get_settings
from app.database import db_fetch_one

bearer_scheme = HTTPBearer()


def _decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_patient(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    payload = _decode_token(credentials.credentials)
    if payload.get("role") != "patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    patient = await db_fetch_one("patients", {"id": payload["sub"]})
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


async def get_current_doctor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    payload = _decode_token(credentials.credentials)
    if payload.get("role") != "doctor":
        raise HTTPException(status_code=403, detail="Doctor access required")
    doctor = await db_fetch_one("doctors", {"id": payload["sub"]})
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


async def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> None:
    settings = get_settings()
    if credentials.credentials != settings.internal_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )
