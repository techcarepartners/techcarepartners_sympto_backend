"""Utilities for slot/date/time computation."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.constants import (
    DAY_TO_INDEX,
    SLOT_ID_TO_WINDOW,
    WINDOW_TO_SLOT_ID,
    DAY_SHORT,
    SLOT_ORDER,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def _slot_to_window_id(slot: dict) -> str | None:
    """Map a slot dict (either {window} or {start}) to a window_id like 'morning'."""
    if "window" in slot and slot["window"]:
        wid = WINDOW_TO_SLOT_ID.get(slot["window"].lower())
        if wid:
            return wid
    if "start" in slot and slot["start"]:
        h = int(slot["start"].split(":")[0])
        if h < 13:
            return "morning"
        elif h < 17:
            return "afternoon"
        else:
            return "evening"
    return None


def get_available_dates(available_slots: list[dict], rejected_windows: dict[str, str] | None = None, doctor_id: str | None = None) -> list[dict]:
    """
    Given a doctor's available_slots JSONB, return a list of bookable dates
    in the next 7 days (tomorrow through +7).

    Each item: { date: "YYYY-MM-DD", display: "Monday, Apr 3", windows: ["morning", ...] }
    Handles both old {day, window} and new {day, start, end} slot formats.
    """
    rejected_windows = rejected_windows or {}
    rejected_window = rejected_windows.get(doctor_id, "") if doctor_id else ""

    # Build map: day_name → [windows]
    windows_by_day: dict[str, list[str]] = {}
    for slot in available_slots:
        day = slot.get("day", "").lower()
        slot_id = _slot_to_window_id(slot)
        if day and slot_id:
            windows_by_day.setdefault(day, []).append(slot_id)

    today = date.today()
    result = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        day_name = d.strftime("%A").lower()
        windows = windows_by_day.get(day_name, [])
        # Filter out rejected window for this doctor
        if rejected_window:
            rejected_slot_id = WINDOW_TO_SLOT_ID.get(rejected_window)
            windows = [w for w in windows if w != rejected_slot_id]
        if not windows:
            continue
        windows_sorted = sorted(windows, key=lambda w: SLOT_ORDER.get(w, 99))
        result.append({
            "date": d.isoformat(),
            "display": f"{d.strftime('%A, %b')} {d.day}",
            "weekday": day_name,
            "windows": windows_sorted,
            "windows_display": [_window_label(w) for w in windows_sorted],
        })
    return result


def get_windows_for_date(available_slots: list[dict], date_str: str, rejected_window: str | None = None) -> list[str]:
    """Return sorted list of slot IDs available for a given date."""
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%A").lower()

    result = []
    for slot in available_slots:
        if slot.get("day", "").lower() == day_name:
            slot_id = _slot_to_window_id(slot)
            if slot_id and slot_id not in result:
                result.append(slot_id)

    if rejected_window:
        rejected_id = WINDOW_TO_SLOT_ID.get(rejected_window.lower())
        result = [w for w in result if w != rejected_id]

    return sorted(result, key=lambda w: SLOT_ORDER.get(w, 99))


def compute_appointment_time(slot_day: str, slot_window: str) -> datetime:
    """
    Compute the next occurrence of slot_day at the start hour of slot_window in IST.
    Returns UTC datetime.
    """
    target_weekday = DAY_TO_INDEX.get(slot_day.lower(), 0)  # Mon=0
    start_hour = _parse_start_hour(slot_window)

    now_ist = datetime.now(IST)
    days_ahead = (target_weekday - now_ist.weekday()) % 7
    if days_ahead == 0 and now_ist.hour >= start_hour:
        days_ahead = 7

    target_date = (now_ist + timedelta(days=days_ahead)).date()
    appointment_ist = datetime(
        target_date.year, target_date.month, target_date.day,
        start_hour, 0, 0, tzinfo=IST
    )
    return appointment_ist.astimezone(UTC)


def format_appointment_time_ist(dt_utc: datetime) -> str:
    """Format a UTC datetime as human-readable IST string."""
    dt_ist = dt_utc.astimezone(IST)
    return dt_ist.strftime("%A, %d %b %Y at %I:%M %p IST")


def build_availability_string(available_slots: list[dict]) -> str:
    """Build 'Mo·Th·Fr' style availability string from available_slots."""
    days_seen = []
    for slot in available_slots:
        day = slot["day"].lower()
        abbr = DAY_SHORT.get(day)
        if abbr and abbr not in days_seen:
            days_seen.append(abbr)
    return "·".join(days_seen)


def build_available_slots_from_days_times(available_days: list[str], time_slots: list[str]) -> list[dict]:
    """
    Cross-product: every selected day × every selected window.
    available_days: ["Mon", "Wed", "Fri"]
    time_slots: ["morning", "afternoon"]
    """
    from app.constants import DAY_ABBR_TO_FULL

    day_full_map = DAY_ABBR_TO_FULL
    time_slot_map = {
        "morning": "9am - 1pm",
        "afternoon": "1pm - 5pm",
        "evening": "5pm - 9pm",
    }
    result = []
    for day_abbr in available_days:
        full_day = day_full_map.get(day_abbr.lower()[:3])
        if not full_day:
            continue
        for slot_id in time_slots:
            window = time_slot_map.get(slot_id)
            if window:
                result.append({"day": full_day, "window": window})
    return result


def build_available_slots_from_configured(configured_slots: dict) -> list[dict]:
    """
    Convert configured_slots from doctor registration flow to available_slots JSONB.
    configured_slots: { "monday": [["09:00 AM", "01:00 PM"]], ... }
    """
    result = []
    for day, time_pairs in configured_slots.items():
        for pair in time_pairs:
            if len(pair) >= 2 and pair[0] and pair[1]:
                window = f"{pair[0]} - {pair[1]}"
                result.append({"day": day.lower(), "window": window})
    return result


def _parse_start_hour(window: str) -> int:
    """Parse start hour from slot window string. '9AM - 1PM' → 9, '1PM - 5PM' → 13."""
    start = window.split("-")[0].strip().upper()
    if "AM" in start:
        h = int(start.replace("AM", "").strip())
        return 0 if h == 12 else h
    elif "PM" in start:
        h = int(start.replace("PM", "").strip())
        return h if h == 12 else h + 12
    return 9


def _window_label(slot_id: str) -> str:
    labels = {
        "morning": "Morning (9–1 PM)",
        "afternoon": "Afternoon (1–5 PM)",
        "evening": "Evening (5–9 PM)",
    }
    return labels.get(slot_id, slot_id)
