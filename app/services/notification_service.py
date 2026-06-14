"""Notification service — email/SMS stubs with structured logging.

In production, wire up SMTP (email) and/or an SMS provider (MSG91, Twilio).
Until then, all notifications are logged so nothing silently disappears.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import get_settings

logger = logging.getLogger(__name__)


async def notify_doctor_new_appointment(
    doctor_id: str,
    doctor_name: str,
    doctor_phone: str,
    appointment_id: str,
    patient_name: str,
    patient_age: int,
    patient_gender: str,
    symptoms_summary: str | None,
    urgency: str,
    slot_day: str,
    slot_window: str,
) -> None:
    """Notify doctor of a new appointment request."""
    subject = "New Appointment Request — Sympto"
    body = (
        f"New Appointment Request\n\n"
        f"Patient: {patient_name}\n"
        f"Age: {patient_age} | Gender: {patient_gender}\n"
        f"Symptoms: {symptoms_summary or 'Not provided'}\n"
        f"Urgency: {urgency}\n"
        f"Requested slot: {slot_day}, {slot_window}\n\n"
        f"To confirm or reject, visit your Sympto dashboard."
    )
    _log_notification("doctor_new_appointment", doctor_phone, subject, body)
    # Future: await _send_email(doctor_email, subject, body)
    # Future: await _send_sms(doctor_phone, f"New patient {patient_name} wants {slot_day} {slot_window}")


async def notify_patient_appointment_confirmed(
    patient_id: str,
    patient_phone: str,
    patient_language: str,
    doctor_name: str,
    slot_day: str,
    slot_window: str,
    clinic_name: str,
) -> None:
    """Notify patient that their appointment was confirmed."""
    from app.utils.messages import get_message

    text = get_message(
        "BOOKING_CONFIRMED",
        patient_language,
        name=doctor_name,
        slot_day=slot_day,
        slot_window=slot_window,
        clinic_name=clinic_name,
    )
    _log_notification("patient_appointment_confirmed", patient_phone, "Appointment Confirmed", text)


async def notify_patient_appointment_rejected(
    patient_phone: str,
    patient_language: str,
    doctor_name: str,
) -> None:
    """Notify patient that their appointment was rejected."""
    from app.utils.messages import get_message

    text = get_message("DOCTOR_REJECTED", patient_language, name=doctor_name)
    _log_notification("patient_appointment_rejected", patient_phone, "Appointment Update", text)


async def notify_doctor_appointment_cancelled(
    doctor_phone: str,
    patient_name: str,
) -> None:
    """Notify doctor that patient cancelled their appointment."""
    from app.utils.messages import DOCTOR_MESSAGES

    text = DOCTOR_MESSAGES["APPOINTMENT_CANCELLED"].format(name=patient_name)
    _log_notification("doctor_appointment_cancelled", doctor_phone, "Appointment Cancelled", text)


async def notify_doctor_approved(doctor_phone: str, approved: bool) -> None:
    """Notify doctor of approval/rejection by admin."""
    from app.utils.messages import DOCTOR_MESSAGES

    key = "DOCTOR_APPROVED" if approved else "DOCTOR_REJECTED_ADMIN"
    text = DOCTOR_MESSAGES[key]
    subject = "Sympto Profile " + ("Approved" if approved else "Update")
    _log_notification("doctor_admin_decision", doctor_phone, subject, text)


async def notify_doctor_membership_changed(doctor_phone: str, granted: bool) -> None:
    """Notify doctor of premium membership grant/revoke."""
    from app.utils.messages import DOCTOR_MESSAGES

    key = "DOCTOR_MEMBER_GRANTED" if granted else "DOCTOR_MEMBER_REVOKED"
    text = DOCTOR_MESSAGES[key]
    _log_notification("doctor_membership_changed", doctor_phone, "Sympto Premium Update", text)


async def send_reminder_to_patient(
    patient_phone: str,
    patient_language: str,
    doctor_name: str,
    appointment_time_str: str,
) -> None:
    from app.utils.messages import get_message

    text = get_message(
        "REMINDER_PATIENT", patient_language, doctor_name=doctor_name, time=appointment_time_str
    )
    _log_notification("patient_reminder", patient_phone, "Appointment Reminder", text)


async def send_reminder_to_doctor(
    doctor_phone: str,
    patient_name: str,
    appointment_time_str: str,
) -> None:
    from app.utils.messages import DOCTOR_MESSAGES

    text = DOCTOR_MESSAGES["REMINDER_DOCTOR"].format(
        patient_name=patient_name, time=appointment_time_str
    )
    _log_notification("doctor_reminder", doctor_phone, "Appointment Reminder", text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_notification(event: str, recipient: str, subject: str, body: str) -> None:
    logger.info(
        "[NOTIFICATION] event=%s recipient=%s subject=%r body_preview=%r",
        event,
        recipient,
        subject,
        body[:100],
    )


async def _send_email(to_email: str, subject: str, body: str) -> None:
    """Send an email via SMTP. Call only when SMTP is configured."""
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_user:
        logger.warning("SMTP not configured — email not sent to %s", to_email)
        return

    import asyncio

    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, to_email, msg.as_string())

    try:
        await asyncio.to_thread(_send)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)


# ── In-app notification helper ─────────────────────────────────────────────────

async def create_notification(
    recipient_role: str,
    type: str,
    title: str,
    body: str,
    recipient_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Insert a row into the notifications table (fire-and-forget, never raises)."""
    try:
        from app.database import db_insert
        await db_insert("notifications", {
            "recipient_role": recipient_role,
            "recipient_id": recipient_id,
            "type": type,
            "title": title,
            "body": body,
            "is_read": False,
            "metadata": metadata or {},
        })
    except Exception as exc:
        logger.error("create_notification failed: %s", exc)
