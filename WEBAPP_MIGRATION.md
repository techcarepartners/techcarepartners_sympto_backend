# Sympto — Complete Web App Migration Specification

> **Purpose:** This document is the single source of truth for migrating the Sympto WhatsApp chatbot to a web application. Every message, state, transition, template, flow, database table, business rule, and edge case from the original codebase is captured here. A Codex agent should be able to read this document and build an exact functional replica as a REST API + frontend, replacing every Meta/WhatsApp dependency with equivalent web API endpoints.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack (Current)](#2-technology-stack-current)
3. [Database Schema (Complete)](#3-database-schema-complete)
4. [Patient Flow — Complete State Machine](#4-patient-flow--complete-state-machine)
5. [Doctor Flow — Complete State Machine](#5-doctor-flow--complete-state-machine)
6. [WhatsApp Flows → Web Form Equivalents](#6-whatsapp-flows--web-form-equivalents)
7. [Message Templates (HSM) → Email/SMS Equivalents](#7-message-templates-hsm--emailsms-equivalents)
8. [LLM Symptom Analysis Engine](#8-llm-symptom-analysis-engine)
9. [All User-Facing Messages (Every Language)](#9-all-user-facing-messages-every-language)
10. [API Endpoints to Build](#10-api-endpoints-to-build)
11. [Business Rules & Edge Cases](#11-business-rules--edge-cases)
12. [Environment Variables](#12-environment-variables)
13. [Reminder System](#13-reminder-system)
14. [Admin Operations](#14-admin-operations)
15. [Activity Logging Events](#15-activity-logging-events)
16. [Complete Conversation Context Object](#16-complete-conversation-context-object)
17. [Doctor Notification Template (Appointment Request)](#17-doctor-notification-template-appointment-request)
18. [Slot & Availability Data Model](#18-slot--availability-data-model)

---

## 1. Project Overview

**Sympto** is an Indian healthcare platform that connects patients with doctors. In WhatsApp form it uses a chatbot; the web app must replicate all chatbot logic via REST APIs.

**Core Actors:**
- **Patient** — finds doctors by describing symptoms or browsing specialties, books appointments
- **Doctor** — registers, sets availability, confirms or rejects appointment requests
- **Admin** — approves/rejects doctor profiles, grants Premium membership

**Core Journey:**
1. Patient opens the app → greeted by language picker
2. Patient selects language → fills profile form (name, age, gender, city, pincode)
3. Patient hits main menu → 5 options (Symptoms Analysis, Browse Doctors, My Appointments, Update Profile, Change Language)
4. Patient describes symptoms → LLM (Gemini) asks 3–13 follow-up questions → recommends specialist
5. System shows a list/carousel of matching doctors (filtered by patient's pincode → city → all India)
6. Patient picks a doctor → picks a date (next 7 days) → picks a time window
7. Appointment created with status `pending` → doctor receives notification
8. Doctor taps Confirm/Reject → patient is notified
9. If rejected → patient can pick same doctor (different slot) or different doctor
10. 2 hours before appointment → both patient and doctor receive reminders

---

## 2. Technology Stack (Current)

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web Framework | FastAPI + Uvicorn |
| Database | Supabase (PostgreSQL via REST) |
| ORM / Client | Supabase Python SDK (sync, wrapped in `asyncio.to_thread`) |
| LLM | Google Gemini 2.5 Flash Lite / 2.5 Flash / 1.5 Flash via LiteLLM |
| Messaging | WhatsApp Cloud API (Meta) |
| Scheduling | Supabase pg_cron (calls `/internal/send-reminders` every 5 min) |
| Storage | Supabase Storage bucket `doctor-photos` |
| Hosting | Render.com or Vercel (serverless) |
| Encryption | RSA-OAEP + AES-GCM (for WhatsApp Flows) |

**Migration Target:** Replace WhatsApp Cloud API + Flows with REST API endpoints that any frontend (React, React Native, Flutter) can consume.

---

## 3. Database Schema (Complete)

### 3.1 Table: `doctors`

```sql
CREATE TABLE doctors (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number     TEXT UNIQUE NOT NULL,   -- KEEP as "phone_number" in webapp
    name                TEXT NOT NULL,
    registration_number TEXT,
    year_register       TEXT,
    specialization      TEXT NOT NULL,          -- lowercase, e.g. "cardiologist"
    photo_url           TEXT,                   -- Supabase Storage URL or null
    is_approved         BOOLEAN NOT NULL DEFAULT false,
    is_member           BOOLEAN NOT NULL DEFAULT false,  -- Premium: shown first in results
    multi_clinic        BOOLEAN NOT NULL DEFAULT false,
    registered_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    vacation_start      TIMESTAMPTZ,
    vacation_end        TIMESTAMPTZ
);
```

**Indexes:** `whatsapp_number`, `specialization`

**Notes:**
- `is_approved = false` means doctor is pending admin review and NOT visible to patients
- `is_member = true` means doctor appears first in search results (Premium tier)
- `multi_clinic = true` when the doctor has 2+ clinic rows in the `clinics` table
- `vacation_start` / `vacation_end`: doctor is hidden from patients during this window
- Photo stored in Supabase Storage bucket `doctor-photos`; `photo_url` is a public URL
- Default placeholder photo URL: `https://mckhpzxslescidjbqpxp.supabase.co/storage/v1/object/public/doctor-photos/placeholder.jpeg`

---

### 3.2 Table: `clinics`

```sql
CREATE TABLE clinics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    clinic_name     TEXT NOT NULL,
    city            TEXT NOT NULL,
    pincode         TEXT NOT NULL,
    state           TEXT NOT NULL,
    available_slots JSONB NOT NULL DEFAULT '[]',
    address         TEXT NOT NULL DEFAULT '',
    maps            TEXT NOT NULL DEFAULT '',     -- Google Maps URL
    is_active       BOOLEAN NOT NULL DEFAULT true,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Indexes:** `doctor_id`, `pincode`, `city`

**`available_slots` JSONB format:**
```json
[
  {"day": "monday", "window": "9am - 1pm"},
  {"day": "monday", "window": "5pm - 9pm"},
  {"day": "wednesday", "window": "9am - 1pm"},
  {"day": "friday", "window": "1pm - 5pm"}
]
```

**Valid window values:**
- `"9am - 1pm"` → Morning (9AM–1PM)
- `"1pm - 5pm"` → Afternoon (1PM–5PM)
- `"5pm - 9pm"` → Evening (5PM–9PM)

**Notes:**
- A single-clinic doctor has exactly 1 row in `clinics` with `is_active = true`
- `is_active = false` / `archived_at != null` means clinic is soft-deleted
- Doctor discovery queries against `clinics` (not `doctors`) for location fields

---

### 3.3 Table: `patients`

```sql
CREATE TABLE patients (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  TEXT UNIQUE NOT NULL,   -- KEEP as "phone_number" in webapp
    name             TEXT NOT NULL,
    age              INTEGER NOT NULL,
    gender           TEXT NOT NULL CHECK (gender IN ('male', 'female', 'other')),
    state            TEXT,
    city             TEXT NOT NULL,
    pincode          TEXT NOT NULL,
    language         TEXT,                   -- 'hinglish' | 'hindi' | 'english' | null
    registered_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Index:** `whatsapp_number`

**Notes:**
- `language` is the patient's preferred UI language (stored on first profile save, never overwritten on profile updates)
- In the webapp, `whatsapp_number` column should be renamed to `phone_number` or `user_id`

---

### 3.4 Table: `appointments`

```sql
CREATE TABLE appointments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id       UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id        UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    clinic_id        UUID REFERENCES clinics(id),        -- which clinic the appointment is at
    slot_day         TEXT NOT NULL,    -- e.g. "Monday" (title-case weekday name)
    slot_window      TEXT NOT NULL,    -- e.g. "9AM - 1PM"
    appointment_time TIMESTAMPTZ,     -- computed when doctor confirms (IST → UTC stored)
    symptoms_summary TEXT,            -- LLM-generated 1-2 sentence summary
    urgency          TEXT NOT NULL DEFAULT 'routine' CHECK (urgency IN ('routine', 'urgent', 'emergency')),
    status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'cancelled')),
    reminder_sent    BOOLEAN NOT NULL DEFAULT false,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Indexes:** `patient_id`, `doctor_id`, composite `(status, appointment_time, reminder_sent)` for reminder queries

**`appointment_time` computation (when doctor confirms):**
```python
# Find the next occurrence of slot_day at the start hour of slot_window (IST)
# Example: slot_day="Monday", slot_window="9AM - 1PM"
# → next Monday at 09:00 IST
# If today IS Monday but 9AM has passed → next Monday (+7 days)
```

**`slot_window` display mapping:**
| DB Value | Display Label |
|---|---|
| `9AM - 1PM` | Morning (9–1 PM) |
| `1PM - 5PM` | Afternoon (1–5 PM) |
| `5PM - 9PM` | Evening (5–9 PM) |

---

### 3.5 Table: `conversations`

```sql
CREATE TABLE conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  TEXT UNIQUE NOT NULL,
    role             TEXT NOT NULL DEFAULT 'patient' CHECK (role IN ('patient', 'doctor')),
    state            TEXT NOT NULL DEFAULT 'IDLE',
    context          JSONB NOT NULL DEFAULT '{}',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()  -- auto-updated by trigger
);
```

**Index:** `whatsapp_number`, `updated_at`

**Purpose:** Tracks which state the user is currently in. In the webapp, this becomes the session/conversation state per user session.

**Trigger:** `updated_at` is automatically refreshed on every UPDATE via a PostgreSQL trigger.

---

### 3.6 Table: `conversation_sessions`

```sql
CREATE TABLE conversation_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  TEXT NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at         TIMESTAMPTZ,
    final_state      TEXT,      -- last state when session closed
    end_reason       TEXT,      -- 'confirmed' | 'cancelled' | 'no_doctors' | 'timeout' | 'reset' | 'new_booking'
    context_snapshot JSONB NOT NULL DEFAULT '{}'
);
```

**Purpose:** Analytics. One row per booking attempt. Created when patient taps "Symptoms Analysis" or "Browse Doctors". Closed when booking concludes (confirm, cancel, no-doctors, timeout).

---

### 3.7 Table: `messages`

```sql
CREATE TABLE messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  TEXT NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    message_type     TEXT NOT NULL,   -- 'text' | 'button_reply' | 'nfm_reply' | 'image' | 'buttons' | 'carousel' | 'flow' | 'list'
    content          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Purpose:** Complete message log for support and analytics.

---

### 3.8 Table: `activity_logs`

```sql
CREATE TABLE activity_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  TEXT,       -- actor; NULL for system-level events
    role             TEXT,       -- 'patient' | 'doctor' | 'system'
    event            TEXT NOT NULL,   -- snake_case event name
    detail           JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Full list of event names:** See [Section 15](#15-activity-logging-events).

---

### 3.9 Table: `webhook_message_ids` (Dedup)

```sql
-- Implied by claim_webhook_message(message_id) function
-- Stores claimed message IDs to prevent double-processing WhatsApp retries
-- In webapp: deduplicate by request ID or idempotency key
```

---

## 4. Patient Flow — Complete State Machine

### 4.1 States

| State | Description |
|---|---|
| `IDLE` | Entry point. No active session. |
| `AWAITING_LANGUAGE` | Waiting for user to pick language (new users only). |
| `AWAITING_PROFILE_FLOW` | Waiting for patient profile form submission. |
| `SHOWING_MENU` | Main menu displayed. Waiting for menu option. |
| `COLLECTING_SYMPTOMS` | Waiting for symptom text input. |
| `COLLECTING_FOLLOWUP` | LLM asked a follow-up question, waiting for answer. |
| `SHOWING_DOCTORS` | Doctor carousel shown. Waiting for "Book" button tap. |
| `AWAITING_SLOT_FLOW` | Date picker shown. Waiting for date selection. |
| `AWAITING_SLOT_TIME` | Time buttons shown. Waiting for time selection. |
| `CONFIRMING` | Appointment pending, waiting for doctor to confirm/reject. |
| `REJECTION_CHOICE` | Doctor rejected — patient choosing same doctor vs other doctors. |
| `VIEWING_APPOINTMENTS` | Appointment history shown. Waiting for cancel action or back. |
| `CANCELLING_APPOINTMENT` | Cancel confirmation prompt shown. |
| `BROWSING_SPECIALTY` | Specialty picker shown. Waiting for specialty selection. |

**Session Timeout:** 3 hours of inactivity → auto-reset to `IDLE`. Open analytics session is closed with `end_reason = "timeout"`.

---

### 4.2 State: `IDLE`

**Entry trigger:** Any message from a new or returning user whose conversation is IDLE.

**Logic:**
```
IF patient record exists in DB:
    → Load their preferred_language
    → Show main menu (SHOWING_MENU state)
    → Log: patient_entered_menu
ELSE:
    → Show language picker (3 buttons)
    → State: AWAITING_LANGUAGE
    → Log: new_user_first_contact
```

**Web API equivalent:**
```
GET /api/patient/session
Response: { state: "IDLE" | "SHOWING_MENU", hasProfile: bool, language: string | null }
```

---

### 4.3 State: `AWAITING_LANGUAGE`

**Entry trigger:** New user (no patient record). Language picker displayed.

**Input:** One of 3 language buttons: `lang_english`, `lang_hindi`, `lang_hinglish`

**Mapping:**
- `lang_english` → `"english"`
- `lang_hindi` → `"hindi"`
- `lang_hinglish` → `"hinglish"`

**Logic after selection:**
```
IF is_language_change == true (returning user changing language):
    → Update patients.language = new_language
    → Show: "Language updated." message
    → Show main menu
    → State: SHOWING_MENU
ELSE (new user):
    → Send welcome message in chosen language
    → Open patient profile form
    → State: AWAITING_PROFILE_FLOW
    → Context: { preferred_language: "english" | "hindi" | "hinglish" }
```

**Welcome message (English):** `"I'll help you find the right doctor. I just need a little information first — please fill in the form below."`

**If invalid input:** Re-show the 3 language buttons.

---

### 4.4 State: `AWAITING_PROFILE_FLOW`

**Entry trigger:** After language selection for new user, OR when returning user taps "Update Profile".

**Input:** Patient profile form submission containing:

| Field | Key | Type | Validation |
|---|---|---|---|
| Full Name | `full_name` | string | strip whitespace |
| Age | `age` | integer | parse from string |
| Gender | `gender` | string | lowercase; one of `male`, `female`, `other` |
| State | `state` | string | lowercase |
| City | `city` | string | lowercase |
| Pincode | `pincode` | string | 6-digit string |

**Logic:**
```
IF existing patient record:
    → Update name, age, gender, city, state, pincode (DO NOT overwrite language)
    → Log: patient_profile_updated
ELSE:
    → Create new patient record with all fields + language from context
    → Set conversation role = 'patient'
    → Log: patient_registered
→ Show main menu
→ State: SHOWING_MENU
→ Context: { preferred_language: language }
```

**If non-form message received while in this state:**
- Reply: `"Please complete the profile form first. After that you can do a Symptoms Analysis."`
- Stay in `AWAITING_PROFILE_FLOW`

---

### 4.5 State: `SHOWING_MENU`

**Entry trigger:** After profile completion, or after returning from any flow.

**Menu options displayed (as list/buttons):**

| Button ID | Label (English) | Label (Hinglish) | Label (Hindi) |
|---|---|---|---|
| `book_appointment` | Symptoms Analysis | Syptoms Analysis | लक्षणों का विश्लेषण |
| `browse_doctors` | Browse Doctors | Doctor Browse Karein | डॉक्टर ब्राउज़ करें |
| `view_appointments` | My Appointments | Mere Appointments | मेरी अपॉइंटमेंट |
| `update_profile` | Update Profile | Profile Update | प्रोफ़ाइल अपडेट |
| `change_language` | Change Language | Change Language / भाषा बदलें | Change Language |

**Menu prompt:** `"Hello {name}. What would you like to do today?"`

**On `book_appointment`:**
```
→ Close any existing open session (end_reason = "new_booking")
→ Create new conversation_sessions row
→ Context: { session_id, preferred_language }
→ Send: "Okay {name}. What problem are you experiencing? Please describe your symptoms in detail."
→ State: COLLECTING_SYMPTOMS
→ Log: booking_session_started
```

**On `browse_doctors`:**
```
→ State: BROWSING_SPECIALTY
→ Show specialty picker list
```

**On `view_appointments`:**
```
→ Fetch last 3 active appointments (status=pending OR confirmed)
→ Show formatted appointment list (numbered: Dr. Name, day, window, status)
→ IF active appointments exist:
    → Show buttons: [Back to Menu] [Cancel Appointment]
    → State: VIEWING_APPOINTMENTS
  ELSE:
    → Stay on menu (no state change needed)
```

**On `update_profile`:**
```
→ Fetch patient's current profile
→ Pre-fill form fields
→ Open profile form (update variant)
→ State: AWAITING_PROFILE_FLOW
```

**On `change_language`:**
```
→ Show 3 language buttons
→ State: AWAITING_LANGUAGE
→ Context: { is_language_change: true, preferred_language: current_lang }
```

**On non-menu input:**
- Reply: `"Please use the menu options below."`
- Re-show the menu

---

### 4.6 State: `COLLECTING_SYMPTOMS`

**Entry trigger:** Patient tapped "Symptoms Analysis".

**Input expected:** Free text describing symptoms.

**Logic:**
```
IF message_type != "text":
    → Reply: "Please describe your symptoms in text."
    → Stay in COLLECTING_SYMPTOMS

ELSE:
    → Call LLM: analyze_symptoms(symptoms_text, language, patient_info)
    → Log: symptoms_submitted, llm_analysis_complete
    → IF LLM error:
        → Reply: "The AI service is currently busy. Please try again in a moment."
        → Stay in COLLECTING_SYMPTOMS (user can retry)
    → IF is_emergency == true:
        → FIRST send emergency warning message
    → IF followup_question != null:
        → Context: { symptoms, followup_turns: [{role:"question", content: Q}], llm_result }
        → State: COLLECTING_FOLLOWUP
        → Send: the followup_question text
    → ELSE (no follow-up needed):
        → Call _find_and_show_doctors()
```

---

### 4.7 State: `COLLECTING_FOLLOWUP`

**Entry trigger:** LLM returned a `followup_question` (needs more information).

**Input expected:** Free text answer.

**If non-text message received:** Re-send the last unanswered question.

**Logic:**
```
→ Append patient's answer to followup_turns
→ Count answered turns (role == "answer")
→ force_conclude = (answered_turns >= MAX_FOLLOWUP_TURNS=13)

→ Call LLM: analyze_symptoms(original_symptoms, followup_turns, language, force_conclude)

QUALITY GATES (code-level, not LLM):
  Gate 1 — Specialist concluded too early:
    IF followup_question is null AND answered_turns < 3 AND NOT force_conclude:
        → Re-call LLM with force_followup_hint=True to force another question
  
  Gate 2 — General Physician requires minimum 5 answered questions:
    IF followup_question is null AND "General Physician" in specializations 
       AND answered_turns < 5 AND NOT force_conclude:
        → Re-call LLM with force_followup_hint=True to force another question

→ Append new followup_question to followup_turns (if any)
→ Update context with new llm_result and followup_turns

→ IF is_emergency:
    → Send emergency warning

→ IF followup_question != null:
    → Stay in COLLECTING_FOLLOWUP
    → Send: the question text
→ ELSE:
    → Call _find_and_show_doctors()
```

---

### 4.8 Doctor Discovery: `_find_and_show_doctors()`

**Called from:** `COLLECTING_FOLLOWUP` (after LLM concludes), `COLLECTING_SYMPTOMS` (if no follow-up), `BROWSING_SPECIALTY`.

**Input:** `LLMResult` object containing specializations, patient's pincode + city.

**Doctor lookup (3-level fallback per specialization):**
```
Level 1: SELECT doctors WHERE specialization=spec AND clinic.pincode=patient_pincode AND is_approved AND NOT on_vacation
Level 2 (if empty): Same but clinic.city=patient_city
Level 3 (if empty): SELECT all approved doctors with matching specialization, any location
```

**If fallback reached level 3:** Show message: `"No {specialization} was found near your location, but these doctors are available:"`

**If ANY specialization returns 0 doctors:** Show: `"No {specialization} is currently available in our system for your symptoms. Please try again later."` → back to menu.

**Before showing doctors:** Always first send the specialist recommendation message:
- Normal: `"Based on your symptoms, I think you should visit a {specialties}."`
- Force-concluded (uncertain): `"I was unable to identify the exact specialist. My best suggestion is to visit a {specialties} — but please share all your symptoms in detail with the doctor."`
- Browse path (summary=None): Skip this message entirely

**Carousel format:** Each doctor card shows:
```
Name: "Dr. {name}"
Body: "{specialization}\n{clinic_name}, {city}"
Availability: "Mo·Th·Fr" (abbreviated days joined by ·)
Button: "Book" → ID: "book_{doctor_id}"
```

**Deduplication:** A doctor appearing in multiple specializations is only shown once.

**Excluded doctors:** Context stores `excluded_doctor_ids` list. Rejected doctors are added here so they don't reappear in the same session.

**After showing carousel:**
- State: `SHOWING_DOCTORS`
- Context: `{ llm_result, doctors_shown: [id...], excluded_doctor_ids: [...] }`
- Log: `doctors_shown`

---

### 4.9 State: `SHOWING_DOCTORS`

**Input:** `button_reply` with ID starting with `book_{doctor_id}`

**Logic:**
```
→ Extract doctor_id from button ID
→ Call _trigger_slot_picker(doctor_id)
```

**If non-book input:** Reply: `"Please tap View Doctors above to select a doctor."`

---

### 4.10 `_trigger_slot_picker()` — Date Selection

**Logic:**
```
→ Fetch doctor by ID
→ Get their available_slots from DB
→ Build windows_by_day dict: { "monday": ["9am - 1pm", "5pm - 9pm"], ... }
→ Filter out previously rejected window for this doctor from context.rejected_slots

→ For each of the next 7 days (tomorrow through +7):
    IF that weekday appears in windows_by_day:
        → Add row: { id: "slot_date_YYYY-MM-DD", title: "Monday, Apr 3", description: "Morning, Evening" }

→ IF no rows (doctor has no availability in next 7 days):
    → Add doctor to excluded_doctor_ids
    → Show: "Dr. {name} has no availability in the next 7 days. Please choose a different doctor."
    → Re-show doctor carousel with updated excluded list
    → Return

→ Context: { selected_doctor_id: doctor_id }
→ State: AWAITING_SLOT_FLOW
→ Send list: "Dr. {name} is available on these days this week:" + date rows
```

---

### 4.11 State: `AWAITING_SLOT_FLOW`

**Input:** `button_reply` with ID starting with `slot_date_YYYY-MM-DD`

**Logic:**
```
→ Extract date string "YYYY-MM-DD"
→ Compute weekday name (e.g. "monday")
→ Fetch doctor's available windows for that day
→ Filter out rejected window for this doctor
→ Sort windows: morning < afternoon < evening
→ Build buttons (max 3):
    { id: "slot_time_morning", title: "Morning (9–1 PM)" }
    { id: "slot_time_afternoon", title: "Afternoon (1–5 PM)" }
    { id: "slot_time_evening", title: "Evening (5–9 PM)" }
→ Context: { pending_slot_date: "YYYY-MM-DD" }
→ State: AWAITING_SLOT_TIME
→ Send: "Pick a time for {date}:" + time buttons
```

**If `book_` button received (patient tapping a doctor card again):** Re-trigger `_trigger_slot_picker` for that doctor.

---

### 4.12 State: `AWAITING_SLOT_TIME`

**Input:** `button_reply` with ID `slot_time_morning`, `slot_time_afternoon`, or `slot_time_evening`

**Slot ID → Display window mapping:**
| slot_id | slot_window (stored in DB) |
|---|---|
| `morning` | `9AM - 1PM` |
| `afternoon` | `1PM - 5PM` |
| `evening` | `5PM - 9PM` |

**Logic:**
```
→ Extract slot_id (morning/afternoon/evening)
→ Get pending_slot_date from context → derive slot_day (weekday name, title-case e.g. "Monday")
→ Map slot_id → slot_window string
→ Get doctor_id from context
→ Check duplicate booking: same patient + doctor + slot_day + status in (pending, confirmed)
    IF duplicate:
        → Show: "⚠️ You already have an appointment with Dr. {name} on {slot_day}. Please choose a different doctor or a different day."
        → State: AWAITING_SLOT_FLOW (they can pick a different date)
        → Return

→ Create appointment in DB:
    { patient_id, doctor_id, slot_day, slot_window, symptoms_summary, urgency, status: "pending" }

→ Context: { appointment_id }
→ State: CONFIRMING
→ Context: { wait_replied: true }

→ Send to DOCTOR: appointment_request template (HSM) with:
    Patient name, age, gender, symptoms summary, urgency, slot_day, slot_window
    → 2 action buttons: [Confirm] [Reject] (button IDs: confirm_appt_{id}, reject_appt_{id})

→ Send to PATIENT: "Dr. {name} has been sent your request. You will receive a message once they confirm."
    + buttons: [Back to Menu] [Cancel Appointment]

→ Log: appointment_created
```

---

### 4.13 State: `CONFIRMING`

**This state represents "waiting for doctor to respond".**

**Patient interaction while in CONFIRMING:**

```
FIRST message from patient (wait_replied == false):
    → Set wait_replied = true
    → Send buttons: [Back to Menu] [Cancel Appointment]
    → "Your appointment request is with the doctor. Please wait for their response."

On btn_id == "btn_back_to_menu":
    → State: SHOWING_MENU
    → Show menu (appointment stays pending — NOT cancelled)

On btn_id == "btn_cancel_appointment" (first tap):
    → Set cancel_confirm_pending = true
    → Send buttons: [Yes, Cancel] [No, Keep Waiting]
    → "Are you sure you want to cancel your appointment request?"

On btn_id == "btn_yes_cancel" (when cancel_confirm_pending == true):
    → Call _cancel_appointment()
    → State: SHOWING_MENU
    → Send: "Your appointment request has been cancelled."
    → Notify doctor: "The patient {name} has cancelled their appointment request."
    → Show menu

On btn_id == "btn_no_keep_waiting" (when cancel_confirm_pending == true):
    → Clear cancel_confirm_pending = false
    → Re-show: "Your appointment request is with the doctor." + original buttons

Any other input (text, unknown button):
    → Re-show waiting prompt with [Back to Menu] [Cancel Appointment] buttons
```

---

### 4.14 Doctor confirms → `notify_patient_confirmed()`

**Triggered by:** Doctor tapping "Confirm" button on appointment notification.

**Logic:**
```
→ Update appointment: status = "confirmed", appointment_time = next_occurrence(slot_day, slot_window)
→ Send to PATIENT (in their preferred language):
    "Your appointment is confirmed.
    Dr. {name}
    {slot_day}, {slot_window}
    {clinic_name}
    Please arrive on time."
    + button: [Back to Menu]
→ Close analytics session (end_reason = "confirmed")
→ State: SHOWING_MENU
→ Send to DOCTOR: "Appointment confirmed. We have notified the patient as well."
→ Log: appointment_confirmed, doctor_confirmed_appointment
```

---

### 4.15 Doctor rejects → `notify_patient_rejected()`

**Triggered by:** Doctor tapping "Reject" button on appointment notification.

**Logic:**
```
→ Update appointment: status = "cancelled"
→ Record rejected slot in context: rejected_slots[doctor_id] = slot_window
→ Send to PATIENT:
    "Dr. {name} has not accepted this slot."
→ Re-show doctor carousel (same specializations, same session context)
→ State: SHOWING_DOCTORS (carousel is shown again)
→ Send to DOCTOR: rejection confirmation
→ Log: appointment_rejected_by_doctor, doctor_rejected_appointment
```

---

### 4.16 State: `REJECTION_CHOICE`

> **Note:** In the current implementation, after rejection the carousel is immediately re-shown (not a choice screen). The `REJECTION_CHOICE` state exists in the state machine but the implementation goes directly to `_find_and_show_doctors`. The buttons `same_doctor` / `other_doctors` were the original design.

**If patient taps `same_doctor`:** Re-trigger slot picker for same doctor (with rejected slot filtered out).

**If patient taps `other_doctors`:** Add doctor to `excluded_doctor_ids` → re-show carousel without that doctor.

---

### 4.17 State: `VIEWING_APPOINTMENTS`

**Entry trigger:** Patient taps "My Appointments" from menu.

**Display format:**
```
*Your recent appointments:*

1. *Dr. {name}*
   {slot_day}, {slot_window}
   Confirmed/Pending
```

**Then show buttons:**
- `btn_back_to_menu` → Back to Menu
- `btn_want_to_cancel` → Cancel Appointment

**On `btn_want_to_cancel`:**
```
→ Fetch cancellable appointments (status=pending OR confirmed)
→ Show individual appointment buttons (max 3):
    { id: "cancel_appt_{id}", title: "Dr. {name} Mon 9AM"[:20] }
→ Stay in VIEWING_APPOINTMENTS
```

**On `cancel_appt_{id}`:**
```
→ Context: { cancel_target_id: appointment_id }
→ State: CANCELLING_APPOINTMENT
→ Send: "Are you sure?" + [Yes, Cancel] [No, Keep Waiting]
```

---

### 4.18 State: `CANCELLING_APPOINTMENT`

**On `btn_yes_cancel`:**
```
→ Update appointment status = "cancelled"
→ Notify doctor: "Patient {name} has cancelled their appointment request."
→ Send to patient: "Your appointment request has been cancelled."
→ State: SHOWING_MENU → Show menu
```

**On anything else:** Proceed back to menu without cancelling.

---

### 4.19 State: `BROWSING_SPECIALTY`

**Entry trigger:** Patient taps "Browse Doctors" from menu.

**Logic:**
```
→ Query DB for all distinct specializations available (from approved, active, non-vacation doctors in patient's area)
→ IF 0 specializations:
    → Show: "No specialists available right now."
    → Back to menu
→ IF 1 specialization:
    → Auto-select it → jump to _find_and_show_doctors
→ ELSE:
    → Paginate: 8 per page + "More Specialists →" + "Back to Menu"
    → Show as list
    → State: BROWSING_SPECIALTY
    → Context: { browse_page: 0 }
```

**On specialty selection (ID: `spec_{specialization}`):**
```
→ Close any open session
→ Create new analytics session
→ Build synthetic LLMResult:
    { specializations: [spec], display_names: [spec.title()], summary: None,
      urgency: "routine", is_emergency: false, followup_question: null }
→ (summary=None signals browse origin → skips "Based on symptoms" text)
→ _find_and_show_doctors()
→ Log: browse_specialty_selected
```

---

## 5. Doctor Flow — Complete State Machine

### 5.1 States

| State | Description |
|---|---|
| `IDLE` | Default state. Waiting for registration trigger or update command. |
| `AWAITING_REGISTRATION_FLOW` | Registration form open. Waiting for submission. |

### 5.2 Registration Trigger

**Trigger text (exact):**
```
"Please do not edit this message and send it as is if you want to join Sympto network as a doctor. Thank you!"
```

This text is sent when a doctor scans the QR code generated by `scripts/generate_qr.py`. In the webapp, replace with a dedicated doctor registration URL.

**Logic on trigger text:**
```
→ Check if doctor already registered (by phone number)
→ IF already registered:
    → Send: "You are already registered with us. ✅ To update your slots, please send Update availability."
    → Stay in IDLE
→ ELSE:
    → Log: doctor_registration_started
    → Send: "Welcome. To register with Sympto network, please fill in the form below."
    → Open doctor registration flow/form
    → State: AWAITING_REGISTRATION_FLOW
    → Set conversation role = 'doctor'
```

**Update availability trigger text:** `"update availability"`

```
→ Load existing doctor data
→ Pre-fill form with current values
→ Open registration flow/form
→ State: AWAITING_REGISTRATION_FLOW
→ Log: doctor_availability_update_started
```

**Any other text from a doctor in IDLE:**
```
→ Send: "Namaste! 😊 To confirm/reject appointments use the notification buttons.
         To update your slots, send Update availability."
```

---

### 5.3 State: `AWAITING_REGISTRATION_FLOW`

**Input:** Doctor registration form submission.

**Form fields:**

| Field | Key | Description |
|---|---|---|
| Name | `name` | Doctor's full name |
| Registration Number | `registration_number` | Medical council registration number |
| Year of Registration | `year_register` | Year registered |
| Specialization | `specialization` | From valid list (see below) |
| State | `state` | lowercase |
| City | `city` | lowercase |
| Pincode | `pincode` | 6-digit string |
| Clinic Name | `clinic_name` | lowercase |
| Available Days | `available_days` | List of abbreviated day names: `["Mon", "Wed", "Fri"]` |
| Time Slots | `time_slots` | List of IDs: `["morning", "afternoon", "evening"]` |

**Valid specializations (exact values stored in DB, all lowercase):**
```
cardiologist, dermatologist, ent, general physician, gynaecologist,
neurologist, ophthalmologist, orthopaedic, paediatrician, psychiatrist, 
urologist, other
```

**Available_slots computation:**
```python
# Map day abbreviations to full day names (lowercase)
day_full_map = {
    "mon": "monday", "tue": "tuesday", "wed": "wednesday",
    "thu": "thursday", "fri": "friday", "sat": "saturday", "sun": "sunday"
}
# Map time slot IDs to window strings
time_slot_map = {
    "morning":   "9am - 1pm",
    "afternoon": "1pm - 5pm",
    "evening":   "5pm - 9pm"
}
# Cross-product: every selected day × every selected window
available_slots = [
    {"day": full_day, "window": window}
    for day_abbr in available_days
    for window in [time_slot_map[t] for t in time_slots]
    full_day = day_full_map[day_abbr.lower()[:3]]
]
```

**Logic after form submission:**
```
→ Upsert doctor record (update if exists, create if new)
→ State: IDLE
→ Send: "✅ Application Submitted! We've received your registration. Our team will review 
         your details and notify you once your profile is live. When someone books an 
         appointment, you will receive a notification here. 
         To update your slots, send Update availability."
→ Log: doctor_registration_complete
```

**New doctor is NOT visible to patients until admin approves (`is_approved = true`).**

---

### 5.4 Doctor Appointment Confirmation/Rejection

**Triggered by:** Doctor tapping action buttons on the appointment notification message.

**Button ID format:**
- Confirm: `confirm_appt_{appointment_id}`
- Reject: `reject_appt_{appointment_id}`

**These are handled BEFORE role-based routing** (highest priority in webhook router).

**On Confirm (`confirm_appt_{id}`):**
```
→ Fetch appointment by ID
→ Compute appointment_time = next_occurrence(slot_day, slot_window) in IST
→ Update appointment: { status: "confirmed", appointment_time: computed_datetime }
→ Notify patient: BOOKING_CONFIRMED message
→ Send to doctor: "Appointment confirmed. We have notified the patient as well."
→ Log: doctor_confirmed_appointment, appointment_confirmed
```

**On Reject (`reject_appt_{id}`):**
```
→ Update appointment: { status: "cancelled" }
→ Load patient's conversation context
→ Call notify_patient_rejected():
    → Record rejected slot in patient's context
    → Send rejection message to patient
    → Re-show doctor carousel to patient
→ Send to doctor: "We have rejected the appointment request. Patient has been informed 
                   that you are not available at the requested time, and to choose a 
                   different slot or doctor."
→ Log: doctor_rejected_appointment, appointment_rejected_by_doctor
```

---

### 5.5 Doctor Additional Features

These are menu items accessible to the doctor via WhatsApp text commands or buttons. In the webapp, expose as authenticated doctor dashboard pages/APIs.

#### Doctor Menu (via WhatsApp buttons/text)

| Command / Button | Action |
|---|---|
| "update availability" | Open availability update form (pre-filled) |
| "add clinic" | Open add-clinic form for multi-clinic setup |
| "my appointments" | Open upcoming appointments flow |
| "update profile" | Open name + specialization update form |
| "vacation" | Open vacation date picker (start + end) |

#### Vacation Mode

**Vacation flow fields:** `vacation_start` (date picker), `vacation_end` (date picker)

**On vacation form submit:**
```
→ Validate: end_date >= start_date (else: "End date cannot be before start date.")
→ Update doctors: { vacation_start, vacation_end }
→ Send: "Leave saved! 🏖️ You won't appear to patients from {start} to {end}."
```

**Cancel vacation:**
```
→ Update doctors: { vacation_start: null, vacation_end: null }
→ Send: "Leave cancelled. You're now visible to patients again. ✅"
```

**During vacation:** Doctor is excluded from all patient-facing search results.

#### Multi-Clinic Support

Doctors can have 2+ clinics. The registration flow now has screens:
1. `DOCTOR_PROFILE` — name, registration number, year, specialization
2. `CLINIC_DETAILS` — clinic name, address, state, city, pincode, Google Maps URL
3. `SELECT_DAYS` — checkbox group of weekdays
4. `DAY_{MON|TUE|WED|THU|FRI|SAT|SUN}` — time pickers for each selected day (morning_start, morning_end, afternoon_start, afternoon_end, evening_start, evening_end)
5. `CONFIRM` — summary screen showing the complete schedule

Each day screen has three period pairs (morning/afternoon/evening), each with a start and end time dropdown. Empty periods are skipped.

**Window format from new flow:** `"{start} - {end}"` where start/end are 12-hour time strings like `"09:00 AM"`.

---

## 6. WhatsApp Flows → Web Form Equivalents

Each WhatsApp Flow is a multi-screen form. In the webapp, replace each with a form page or modal.

### 6.1 Patient Profile Form (New + Update)

**Flow files:** `patient_profile_new_flow.json`, `patient_profile_update_flow.json`

**Screen: `PATIENT_PROFILE`**

| Field | Type | Options / Validation |
|---|---|---|
| Full Name | Text input | Required |
| Age | Number input | Integer |
| Gender | Dropdown/Radio | Male, Female, Other |
| State | Dropdown | Indian states list |
| City | Text input | Required |
| Pincode | Number input | 6-digit |

**Language variants:** 3 separate flow IDs for English, Hindi, Hinglish. In webapp, handle via i18n/locale.

**Form token format (for routing):** `patient_profile_{wa_number}_{hex8}` — in webapp use JWT or session ID.

**Update variant:** Pre-fill all fields with existing patient data. Language field NOT updated on profile edit.

---

### 6.2 Doctor Registration Flow (11 screens)

**Flow file:** `doctor_registration_flow.json`

**Screen sequence:**
1. `DOCTOR_PROFILE` → name, registration number, year, specialization
2. `CLINIC_DETAILS` → clinic name, address, state, city, pincode, Google Maps URL
3. `SELECT_DAYS` → checkbox group of days: monday–sunday
4. `DAY_MON` (if Monday selected) → morning_start, morning_end, afternoon_start, afternoon_end, evening_start, evening_end (all dropdowns, optional)
5. `DAY_TUE` (if Tuesday selected) → same structure
6. ... (one screen per selected day, in day order)
7. `CONFIRM` → shows text summary of entire schedule

**Server-side flow:** The server receives data_exchange calls at each screen transition. Server accumulates state in `context["reg_flow_session"]` across calls.

**Final submission (after all day screens):** Server saves doctor + clinic to DB, returns CONFIRM screen with schedule summary text.

**Time dropdown values:** `"09:00 AM"`, `"10:00 AM"`, ..., `"09:00 PM"` (every hour)

**Window computation:** `"{start} - {end}"` → e.g. `"09:00 AM - 01:00 PM"`

---

### 6.3 Add Clinic Flow (same structure as registration screens 2+)

**Flow file:** `add_clinic_flow.json`

**Screen sequence:**
1. `CLINIC_DETAILS` → clinic name, address, state, city, pincode, Google Maps URL
2. `SELECT_DAYS` → checkbox group
3. `DAY_*` screens for each selected day
4. `CONFIRM` → schedule summary

**Three modes (stored in context):**
- `mode = "new"` → insert new clinic row
- `mode = "update_single"` → update specific clinic by `clinic_id`
- `mode = "update_all"` → update all clinics for this doctor with same slots

**On completion:**
- If doctor now has 2+ clinics → set `doctors.multi_clinic = true`
- Log: `doctor_clinic_added` or `doctor_availability_updated_single` or `doctor_availability_updated_all`
- Send: `"✅ Clinic added successfully! To add another clinic, send add clinic. To update availability, send update availability."`

---

### 6.4 Slot Picker Flow (Patient)

**Flow file:** `slot_picker_flow.json`

> **Note:** In the current code, the slot picker is implemented as a WhatsApp list message (not a Flow). The `slot_picker_flow.json` is the Meta Flow version. The actual running code uses `send_list` + `send_buttons`.

**Webapp equivalent:** A date-time picker form with two steps:
1. Pick available date (list of next 7 days the doctor is available)
2. Pick time window (buttons: Morning / Afternoon / Evening)

**Flow endpoint:** `POST /flows/slots` — encrypted RSA+AES-GCM. Returns available slots for the selected date.

**Three possible screens returned:**
- `SLOT_PICKER` → show radio buttons of slot options for chosen date
- `NO_SLOTS` → no slots available for chosen date

---

### 6.5 Vacation Flow

**Flow file:** `vacation_flow.json`

| Field | Type |
|---|---|
| Vacation Start | Date picker |
| Vacation End | Date picker |

**Actions on confirmation screen:**
- Set leave (new vacation)
- Update leave (change dates)
- Cancel leave (clear vacation dates)

---

### 6.6 Doctor Appointments Flow

**Flow file:** `doctor_appointments_flow.json`

**Screen: `MENU`** — shows counts of pending / confirmed / cancelled appointments with navigation buttons.

**When doctor taps Pending (count > 0):** Shows list of pending appointments with checkbox selection + action dropdown (confirm / reject).

**When doctor taps Confirmed (count > 0):** Shows list of confirmed appointments with reject option.

**Server endpoint:** `POST /flows/doctor-appointments`

**INIT response:** Builds appointment list text for all 3 categories, returns counts and data arrays.

**Data exchange screens:**
- `MENU` → navigate to pending/confirmed/cancelled list or empty screens
- `pending_action` → show confirmation summary screen
- `confirmed_action` → show rejection summary screen
- `rejected_action` → show re-confirmation summary screen

---

### 6.7 Doctor Profile Flow (Read-only)

**Flow file:** `doctor_profile_flow.json`

**Screen: `DOCTOR_PROFILE`** — displays:
- Doctor name
- Specialization
- Clinic 1 (name + city)
- Clinic 2 (name + city, shown if multi_clinic)
- Clinic 3 (name + city, shown if 3+ clinics)

**Triggered from:** appointment_request template button "View Profile".

---

### 6.8 Doctor Update Profile Flow

**Flow file:** `doctor_update_profile_flow.json`

**Editable fields:** Name, Specialization only. Registration number and year are locked.

---

## 7. Message Templates (HSM) → Email/SMS Equivalents

Meta HSM (Highly Structured Messages) are pre-approved templates. In the webapp, replace with email, SMS, or push notifications with equivalent content.

### 7.1 Template: `appointment_request`

**Sent to:** Doctor
**Trigger:** Patient books a slot
**Type:** Notification with action buttons

**Content structure:**
```
Header: "New Appointment Request"

Body:
"Patient: {patient_name}
Age: {patient_age} | Gender: {patient_gender}
Symptoms: {symptoms_summary}
Urgency: {urgency}
Requested slot: {slot_day}, {slot_window}"

Buttons:
- [✅ Confirm] → callback ID: confirm_appt_{appointment_id}
- [❌ Reject] → callback ID: reject_appt_{appointment_id}
- [View Profile] → opens doctor_profile_flow
```

**WhatsApp implementation:**
```python
await whatsapp.send_doctor_notification(
    doctor_number=doctor["whatsapp_number"],
    appointment_id=appointment["id"],
    patient_name=patient["name"],
    patient_age=patient["age"],
    patient_gender=patient["gender"],
    symptoms_summary=symptoms_summary,
    urgency=urgency,
    slot_day=slot_day,
    slot_window=slot_window,
    template_name="appointment_request",
)
```

**API equivalent for webapp:**
```
POST /api/notifications/appointment-request
{
  doctor_id, appointment_id, patient_name, patient_age, patient_gender,
  symptoms_summary, urgency, slot_day, slot_window
}
→ Send email/SMS/push to doctor
→ Return deep link / action URL for confirm and reject
```

---

### 7.2 Template: `appointment_reminder_patient`

**Sent to:** Patient
**Trigger:** 2 hours before appointment (pg_cron every 5 min)
**Condition:** `status = "confirmed"` AND `appointment_time` between `now + 1.5h` and `now + 2.5h` AND `reminder_sent = false`

**Content (language-aware):**

English:
```
⏰ Reminder: Your appointment with Dr. {doctor_name} is at {time}. Please arrive on time.
```

Hinglish:
```
⏰ Reminder: Aapka appointment Dr. {doctor_name} ke saath {time} pe hai. Please time pe pahunchein.
```

Hindi:
```
⏰ याद दिलाना: आपकी अपॉइंटमेंट डॉ. {doctor_name} के साथ {time} पर है। कृपया समय पर पहुंचें।
```

**Time format:** `"Monday, 03 Jan 2026 at 09:00 AM IST"`

---

### 7.3 Template: `appointment_reminder_doctor`

**Sent to:** Doctor
**Trigger:** Same as patient reminder (same appointment, same time)
**Language:** Always English

```
⏰ Reminder: You have an appointment with {patient_name} at {time}.
```

---

## 8. LLM Symptom Analysis Engine

### 8.1 Models & Fallback Chain

```python
_MODEL_FALLBACK_CHAIN = [
    "gemini/gemini-2.5-flash-lite",  # Layer 1: fastest, cheapest
    "gemini/gemini-2.5-flash",       # Layer 2
    "gemini/gemini-1.5-flash",       # Layer 3
]
```

Each model attempted up to 2 times for JSON parse failures. If all 3 layers fail → return default: `General Physician, 70% confidence, routine urgency`.

### 8.2 LLMResult Schema

```python
class LLMResult:
    specializations: list[str]       # 1 or 2, from VALID_SPECIALIZATIONS
    display_names: list[str]         # patient-facing names (e.g. "Gastroenterologist" for "Other")
    confidence_scores: list[int]     # 0–100 per specialization
    summary: Optional[str]           # 1-2 sentence English summary for doctor
    urgency: str                     # "routine" | "urgent" | "emergency"
    is_emergency: bool               # True for life-threatening situations
    followup_question: Optional[str] # Next question, or null if ready to conclude
    was_force_concluded: bool        # True if MAX_FOLLOWUP_TURNS=13 hit
```

### 8.3 Valid Specializations

```python
VALID_SPECIALIZATIONS = {
    "Cardiologist", "Dermatologist", "ENT", "General Physician",
    "Gynaecologist", "Neurologist", "Ophthalmologist", "Orthopaedic",
    "Paediatrician", "Psychiatrist", "Urologist", "Other"
}
```

**Special rule for "Other":** `display_names` contains the actual specialty (e.g. "Gastroenterologist", "Pulmonologist"). `specializations` stays `"Other"` for DB routing.

### 8.4 System Prompt (Exact)

```
You are a medical triage assistant for an Indian healthcare platform.
You receive a patient profile (age, gender) followed by their symptom description and any prior conversation turns.
Your goal is to identify the most appropriate medical specialist(s) for the patient by asking targeted clarifying questions, one at a time, and then routing them to the correct specialist.

SPECIALIST SELECTION — use your medical knowledge:
- Apply clinical reasoning: consider the organ system involved, acuity indicators, demographic risk factors (age, gender), and the presenting symptom pattern.
- Always route to the most specific specialist the symptoms support. General Physician is a last resort — only when symptoms are genuinely non-specific and cannot be attributed to any particular organ or system.
- The valid specializations are: Cardiologist, Dermatologist, ENT, General Physician, Gynaecologist, Neurologist, Ophthalmologist, Orthopaedic, Paediatrician, Psychiatrist, Urologist, Other.
- Use "Other" when the correct specialist is not in this list (e.g. Gastroenterologist, Pulmonologist, Endocrinologist). For "Other" entries, write the actual specialty name in display_names.
- Use patient age and gender to inform urgency and routing: e.g. a child under 14 should generally see a Paediatrician; a 70-year-old with exertional symptoms carries higher cardiac urgency than a 25-year-old.
- Abdominal pain, nausea, vomiting, diarrhea, constipation, bloating, acid reflux, or any digestive/GI tract symptoms → always route to "Other" with display_name "Gastroenterologist". Never use General Physician for these.

FOLLOW-UP QUESTIONING — use your medical knowledge:
- Ask targeted questions that would help you differentiate between plausible specialties for the stated symptoms.
- Ask EXACTLY one short, focused question per turn. Never combine two questions into one message.
- Stop asking and conclude once you have gathered enough information.

RULES:
- MANDATORY FIRST QUESTION: If no prior Q&A turns, you MUST set followup_question to a clarifying question. Never conclude on the first message alone.
- GENERAL PHYSICIAN RULE: General Physician is ONLY acceptable when: (a) AT LEAST 5 follow-up questions answered, AND (b) symptoms genuinely span multiple unrelated organ systems. If fewer than 5 questions answered and best answer is GP, you MUST ask another question.
- Once you have identified a specific non-GP specialist with sufficient confidence, set followup_question to null.
- If {max_turns} or more answered questions, you MUST conclude immediately with followup_question = null.
- Always respond with ONLY raw JSON. No explanation, no markdown, no code fences.
- Never refuse; always pick the best matching specialization(s).

Your response must be exactly this JSON structure:
{"specializations": ["..."], "display_names": ["..."], "confidence_scores": [85], "summary": "...", "urgency": "...", "is_emergency": false, "followup_question": null}
```

### 8.5 User Message Format

```
Patient profile: Age: {age}, Gender: {gender}

Patient's initial symptoms: {symptoms_text}

Doctor's question: {followup_turns[0]["content"]}

Patient's answer: {followup_turns[1]["content"]}

... (alternating question/answer)

[INSTRUCTION: You have gathered enough information. You MUST now provide the final result with followup_question set to null.]
[OVERRIDE: You concluded too early... (force_followup_hint)]
```

### 8.6 Quality Gates (Code-Level)

These gates run AFTER the LLM call, before displaying results:

| Gate | Condition | Action |
|---|---|---|
| Specialist Gate | Any non-GP specialist concluded AND answered_turns < 3 AND NOT force_conclude | Re-call LLM with `force_followup_hint=True` |
| GP Gate | GP returned AND answered_turns < 5 AND NOT force_conclude | Re-call LLM with `force_followup_hint=True` |

### 8.7 LLM Parameters

```python
model: "gemini/gemini-2.5-flash-lite"  # etc.
temperature: 0.7
max_tokens: 1024
```

### 8.8 DB-Stored Prompt Override

The system supports DB-stored prompt overrides with 5-minute TTL cache. Keys:
- `"system_prompt"` → replaces the entire system prompt template
- `"followup_instruction_hinglish"` → replaces the followup_question instruction
- `"followup_instruction_hindi"` → same for Hindi
- `"followup_instruction_english"` → same for English

---

## 9. All User-Facing Messages (Every Language)

### 9.1 Patient Messages

| Key | English | Hinglish | Hindi |
|---|---|---|---|
| `LANGUAGE_PICKER` | "Hello! Welcome to *Sympto*. Please select your preferred language:" | "Namaste! *Sympto* mein swagat hai. Pehle apni bhasha chunein:" | "नमस्ते! *सिम्प्टो* में आपका स्वागत है। पहले अपनी भाषा चुनें:" |
| `WELCOME_NEW` | "I'll help you find the right doctor. I just need a little information first — please fill in the form below." | "Main aapko sahi doctor dhundhne mein help karunga. Pehle thodi si information chahiye — please neeche form fill karein." | "मैं आपको सही डॉक्टर ढूंढने में मदद करूंगा। पहले थोड़ी जानकारी चाहिए — कृपया नीचे फ़ॉर्म भरें।" |
| `MENU_PROMPT` | "Hello *{name}*. What would you like to do today?" | "Namaste *{name}*. Aaj kya karna chahenge?" | "नमस्ते *{name}*। आज क्या करना चाहेंगे?" |
| `BTN_BOOK` | "Symptoms Analysis" | "Syptoms Analysis" | "लक्षणों का विश्लेषण" |
| `BTN_BROWSE_DOCTORS` | "Browse Doctors" | "Doctor Browse Karein" | "डॉक्टर ब्राउज़ करें" |
| `BTN_VIEW` | "My Appointments" | "Mere Appointments" | "मेरी अपॉइंटमेंट" |
| `BTN_UPDATE_PROFILE` | "Update Profile" | "Profile Update" | "प्रोफ़ाइल अपडेट" |
| `BTN_CHANGE_LANGUAGE` | "Change Language / भाषा बदलें" | "Change Language / भाषा बदलें" | "Change Language" |
| `SYMPTOMS_PROMPT` | "Okay *{name}*. What problem are you experiencing? Please describe your symptoms in detail." | "Theek hai *{name}*. Aapko kya problem ho rahi hai? Apne symptoms detail mein describe kijiye." | "ठीक है *{name}*। आपको क्या समस्या हो रही है? अपने लक्षण विस्तार से बताइए।" |
| `FOLLOWUP` | "{question}" | "{question}" | "{question}" |
| `EMERGENCY_WARNING` | "⚠️ *These symptoms sound serious.* If you think this is an emergency, please call *112* now or go to the nearest Emergency Room. Your safety comes first. If you are feeling okay right now, I will find a doctor for you." | "⚠️ *Ye symptoms serious lag rahe hain.* Agar aapko lagta hai ye emergency hai, toh abhi *112* call karein ya nearest Emergency Room jayein. Apni safety sabse pehle. Agar abhi theek ho toh main aapke liye doctor dhundh deta hoon." | "⚠️ *ये लक्षण गंभीर लग रहे हैं।* अगर आपको लगता है यह आपातकाल है, तो अभी *112* पर कॉल करें या नज़दीकी आपातकालीन कक्ष जाएं। आपकी सुरक्षा सबसे पहले। अगर अभी ठीक हैं तो मैं आपके लिए डॉक्टर ढूंढता हूं।" |
| `SPECIALIST_RECOMMENDATION` | "Based on your symptoms, I think you should visit a *{specialties}*." | "Aapke symptoms ke hisaab se, mujhe lagta hai aapko *{specialties}* se milna chahiye." | "आपके लक्षणों के आधार पर, मुझे लगता है आपको *{specialties}* से मिलना चाहिए।" |
| `SPECIALIST_RECOMMENDATION_UNCERTAIN` | "I was unable to identify the exact specialist based on your symptoms. My best suggestion is to visit a *{specialties}* — but please share all your symptoms in detail with the doctor." | "Mujhe aapke symptoms ke basis pe sahi specialist identify karna mushkil tha. Mere best guess ke hisaab se aapko *{specialties}* se milna chahiye — lekin main suggest karunga ki doctor ko apne saare symptoms poori detail mein batayein." | "आपके लक्षणों के आधार पर सही विशेषज्ञ पहचानना मुश्किल था। मेरे अनुसार आपको *{specialties}* से मिलना चाहिए — लेकिन डॉक्टर को पूरी जानकारी दें।" |
| `NO_DOCTORS_FOUND` | "No *{specialization}* is currently available in our system for your symptoms. Please try again later." | "Aapke symptoms ke liye koi *{specialization}* abhi humare system me available nahi hai. Baad mein dobara try karein." | "आपके लक्षणों के लिए कोई *{specialization}* अभी हमारे सिस्टम में उपलब्ध नहीं है। बाद में दोबारा कोशिश करें।" |
| `NO_DOCTORS_LOCAL` | "No *{specialization}* was found near your location, but these doctors are available:" | "Aapki location k paas abhi koi *{specialization}* nahi mila, lekin ye doctors available hain:" | "आपकी location के पास अभी कोई *{specialization}* नहीं मिला, लेकिन ये डॉक्टर उपलब्ध हैं:" |
| `DOCTORS_LIST_BODY` | "These doctors are available 🩺\nSelect one to book an appointment:" | "Ye doctors available hain 🩺\nKisi ek ko select karein aur appointment book karein:" | "ये डॉक्टर उपलब्ध हैं 🩺\nकिसी एक को चुनें और अपॉइंटमेंट बुक करें:" |
| `PICK_A_DAY` | "*Dr. {name}* is available on these days this week:" | "*Dr. {name}* is week mein in dinon available hain:" | "*डॉ. {name}* इस हफ़्ते इन दिनों उपलब्ध हैं:" |
| `BTN_SEE_DAYS` | "See Days" | "Din Dekhein" | "दिन देखें" |
| `NO_SLOTS_THIS_WEEK` | "*Dr. {name}* has no availability in the next 7 days. Please choose a different doctor." | "*Dr. {name}* agle 7 din mein available nahi hain. Please koi aur doctor choose karein." | "*डॉ. {name}* अगले 7 दिनों में उपलब्ध नहीं हैं। कृपया कोई अन्य डॉक्टर चुनें।" |
| `PICK_A_TIME` | "Pick a time for *{date}*:" | "*{date}* ke liye time chunein:" | "*{date}* के लिए समय चुनें:" |
| `APPOINTMENT_PENDING` | "*Dr. {name}* has been sent your request. You will receive a message once they confirm." | "*Dr. {name}* ko request bhej di gayi hai. Jab wo confirm karenge, aapko message aayega." | "*डॉ. {name}* को अनुरोध भेज दिया गया है। जब वे पुष्टि करेंगे, आपको संदेश आएगा।" |
| `APPOINTMENT_WAITING` | "Your appointment request is with the doctor. Please wait for their response." | "Aapki appointment request doctor ke paas hai. Unka response aane ka wait karein." | "आपकी अपॉइंटमेंट का अनुरोध डॉक्टर के पास है। उनके जवाब का इंतज़ार करें।" |
| `BTN_BACK_TO_MENU` | "Back to Menu" | "Menu Par Jayein" | "मेनू पर जाएं" |
| `BTN_CANCEL_APPOINTMENT` | "Cancel Appointment" | "Appointment Cancel Karein" | "अपॉइंटमेंट रद्द करें" |
| `CANCEL_CONFIRM_PROMPT` | "Are you sure you want to cancel your appointment request?" | "Kya aap sach mein apni appointment cancel karna chahte hain?" | "क्या आप सच में अपनी अपॉइंटमेंट रद्द करना चाहते हैं?" |
| `BTN_YES_CANCEL` | "Yes, Cancel" | "Haan, Cancel Karein" | "हाँ, रद्द करें" |
| `BTN_NO_KEEP_WAITING` | "No, Keep Waiting" | "Nahi, Wait Karein" | "नहीं, इंतज़ार करें" |
| `APPOINTMENT_CANCELLED_PATIENT` | "Your appointment request has been cancelled." | "Aapki appointment cancel ho gayi hai." | "आपकी अपॉइंटमेंट रद्द कर दी गई है।" |
| `BOOKING_CONFIRMED` | "Your appointment is confirmed.\n\nDr. *{name}*\n*{slot_day}, {slot_window}*\n*{clinic_name}*\n\nPlease arrive on time." | "Aapki appointment confirm ho gayi.\n\nDr. *{name}*\n*{slot_day}, {slot_window}*\n*{clinic_name}*\n\nPlease time pe pahunchein." | "आपकी अपॉइंटमेंट कन्फ़र्म हो गई।\n\nडॉ. *{name}*\n*{slot_day}, {slot_window}*\n*{clinic_name}*\n\nकृपया समय पर पहुंचें।" |
| `DOCTOR_REJECTED` | "*Dr. {name}* has not accepted this slot. Would you like to see other slots with the same doctor, or try a different doctor?" | "*Dr. {name}* ne abhi ye slot accept nahi ki. Kya aap same doctor ke doosre slot dekhna chahenge, ya kisi aur doctor ko try karein?" | "*डॉ. {name}* ने अभी यह स्लॉट स्वीकार नहीं किया। क्या आप उसी डॉक्टर के दूसरे स्लॉट देखना चाहेंगे, या किसी अन्य डॉक्टर को आज़माएं?" |
| `BTN_SAME_DOCTOR` | "Same Doctor" | "Same Doctor" | "वही डॉक्टर" |
| `BTN_OTHER_DOCTORS` | "Other Doctors" | "Doosre Doctors" | "दूसरे डॉक्टर" |
| `DUPLICATE_BOOKING` | "⚠️ You already have an appointment with *Dr. {name}* on *{slot_day}*. Please choose a different doctor or a different day." | "⚠️ Aapki *Dr. {name}* ke saath *{slot_day}* ko pehle se ek appointment hai. Please doosra doctor ya alag din choose karein." | "⚠️ *डॉ. {name}* के साथ *{slot_day}* को पहले से एक अपॉइंटमेंट है। कृपया दूसरा डॉक्टर या अलग दिन चुनें।" |
| `ASK_CANCEL_APPT` | "Do you want to cancel any of your appointments?" | "Kya aap koi appointment cancel karna chahte hain?" | "क्या आप कोई अपॉइंटमेंट रद्द करना चाहते हैं?" |
| `CANCEL_WHICH_APPT` | "Which appointment would you like to cancel?" | "Kaunsi appointment cancel karni hai?" | "कौन सी अपॉइंटमेंट रद्द करनी है?" |
| `NO_APPOINTMENTS` | "You have no appointments yet. Tap 'Symptoms Analysis' to get started." | "Aapki abhi tak koi appointment nahi hai. 'Syptoms Analysis' karein." | "आपकी अभी तक कोई अपॉइंटमेंट नहीं है। 'लक्षणों का विश्लेषण' करें।" |
| `BROWSE_SPECIALTY_PROMPT` | "Which type of specialist would you like to see?" | "Aap kaun se specialist se milna chahte hain?" | "आप किस विशेषज्ञ से मिलना चाहते हैं?" |
| `NO_SPECIALTIES_AVAILABLE` | "No specialists available right now. Please try 'Symptoms Analysis' instead." | "Abhi koi specialist available nahi. Please 'Symptoms Analysis' try karein." | "अभी कोई विशेषज्ञ उपलब्ध नहीं। कृपया लक्षणों का विश्लेषण आज़माएं।" |
| `BTN_MORE_SPECIALISTS` | "More Specialists →" | "Aur Specialists →" | "और विशेषज्ञ →" |
| `LLM_BUSY` | "The AI service is currently busy. Please try again in a moment." | "Abhi AI service thodi busy hai. Thodi der baad dobara try karein." | "अभी AI सेवा थोड़ी व्यस्त है। थोड़ी देर बाद दोबारा कोशिश करें।" |
| `GENERIC_ERROR` | "Something went wrong. Please try again." | "Kuch problem aayi. Please dobara try karein." | "कुछ समस्या आई। कृपया दोबारा कोशिश करें।" |
| `COMPLETE_PROFILE_FIRST` | "Please complete the profile form first. After that you can do a Symptoms Analysis." | "Please pehle profile form complete karein. Iske baad aap appointments book kar sakte hain." | "कृपया पहले प्रोफ़ाइल फ़ॉर्म पूरा करें। इसके बाद आप अपॉइंटमेंट बुक कर सकते हैं।" |
| `LANGUAGE_CHANGED` | "Language updated." | "Bhasha update ho gayi." | "भाषा अपडेट हो गई।" |
| `CONFIDENCE_LABEL` | "Confident" | "Confident" | "आश्वस्त" |

### 9.2 Doctor Messages (Always English)

| Constant | Text |
|---|---|
| `ALREADY_REGISTERED` | "You are already registered with us. ✅ To update your slots, please send *Update availability*." |
| `DOCTOR_REGISTRATION_PROMPT` | "Welcome. To register with Sympto network, please fill in the form below." |
| `ONBOARDING_DONE` | "✅ *Application Submitted!* We've received your registration. Our team will review your details and notify you once your profile is live. When someone books an appointment, you will receive a notification here. To update your slots, send *Update availability*." |
| `UPDATE_AVAILABILITY_PROMPT` | "To update your availability, please fill in the form below." |
| `DOCTOR_APPROVED` | "✅ *Great news!* Your Sympto profile has been approved. Patients in your area can now find and book appointments with you. You'll receive a WhatsApp notification whenever someone books a slot." |
| `DOCTOR_REJECTED_ADMIN` | "We're sorry — your Sympto application could not be approved at this time. Please contact our support team for more information." |
| `DOCTOR_MEMBER_GRANTED` | "🌟 *Welcome to Sympto Premium!* You are now a verified member. Your profile will be featured at the top of patient searches in your area." |
| `DOCTOR_MEMBER_REVOKED` | "Your Sympto Premium membership has ended. Your profile remains active but will no longer be featured at the top of search results." |
| `DOCTOR_CONFIRMATION_TO_DOCTOR` | "Appointment confirmed. We have notified the patient as well." |
| `DOCTOR_REJECTION_TO_DOCTOR` | "We have rejected the appointment request. Patient has been informed that you are not available at the requested time, and to choose a different slot or doctor." |
| `DOCTOR_APPOINTMENT_CANCELLED` | "The patient *{name}* has cancelled their appointment request." |
| `CLINIC_ADDED` | "✅ Clinic added successfully! To add another clinic, send *add clinic*. To update availability, send *update availability*." |
| `AVAILABILITY_UPDATED` | "Your availability has been updated. ✅ Patients will see your new slots in the finder." |
| `VACATION_NO_LEAVE` | "You have no upcoming leave set." |
| `VACATION_ACTIVE` | "You're on leave: *{start}* → *{end}*" |
| `VACATION_SAVED` | "Leave saved! 🏖️ You won't appear to patients from *{start}* to *{end}*." |
| `VACATION_CANCELLED` | "Leave cancelled. You're now visible to patients again. ✅" |
| `VACATION_INVALID_DATES` | "End date cannot be before start date. Please try again." |

---

## 10. API Endpoints to Build

### 10.1 Authentication

All patient/doctor APIs should use phone number + OTP authentication (or JWT). Admin APIs use a Bearer token (`INTERNAL_SECRET` equivalent).

### 10.2 Patient APIs

```
POST   /api/patient/session           → Create/resume session; return state + profile
POST   /api/patient/language          → { language } → save preference
POST   /api/patient/profile           → { name, age, gender, state, city, pincode } → upsert
GET    /api/patient/profile           → Return patient profile
GET    /api/patient/menu              → Return current state + menu options
POST   /api/patient/symptoms          → { symptoms_text } → call LLM, return { followup_question? | doctors[] }
POST   /api/patient/followup          → { answer } → continue LLM conversation, return same
GET    /api/patient/doctors           → { specialization, pincode, city, page } → return doctor list
POST   /api/patient/select-doctor     → { doctor_id } → return available dates (next 7 days)
POST   /api/patient/select-date       → { doctor_id, date } → return time window options
POST   /api/patient/book              → { doctor_id, slot_day, slot_window } → create appointment
GET    /api/patient/appointments      → Return patient's appointments (last 3 active)
POST   /api/patient/cancel            → { appointment_id } → cancel, notify doctor
POST   /api/patient/language-change   → { language } → update preferred language
GET    /api/patient/specialties       → Return available specializations near patient location
POST   /api/patient/browse-specialty  → { specialization } → return doctors for that spec
```

### 10.3 Doctor APIs

```
POST   /api/doctor/register           → { name, registration_number, year_register, specialization, clinic_name, city, state, pincode, available_days, time_slots } → upsert doctor + clinic
POST   /api/doctor/update-availability → { available_days, time_slots, clinic_id? } → update slots
GET    /api/doctor/profile            → Return doctor profile + clinics
POST   /api/doctor/update-profile     → { name, specialization } → update name/spec only
GET    /api/doctor/appointments       → Return upcoming (pending + confirmed + cancelled)
POST   /api/doctor/confirm            → { appointment_id } → confirm, set appointment_time, notify patient
POST   /api/doctor/reject             → { appointment_id } → cancel, notify patient
POST   /api/doctor/vacation           → { vacation_start, vacation_end } → set vacation
DELETE /api/doctor/vacation           → Clear vacation dates
POST   /api/doctor/clinic             → Add new clinic
PUT    /api/doctor/clinic/{id}        → Update clinic
DELETE /api/doctor/clinic/{id}        → Archive clinic
```

### 10.4 Admin APIs (Bearer Token Protected)

```
GET    /api/admin/pending-doctors           → List unapproved doctors
POST   /api/admin/approve-doctor            → { doctor_id, approved: bool, notify: bool }
POST   /api/admin/set-membership            → { doctor_id, is_member: bool, notify: bool }
POST   /api/admin/send-reminders            → Manually trigger reminder send (or cron)
POST   /api/admin/confirm-appointment       → { appointment_id } → dev/test confirm
POST   /api/admin/reject-appointment        → { appointment_id } → dev/test reject
```

### 10.5 Internal/Cron APIs

```
POST   /internal/send-reminders       → Called every 5 minutes by scheduler
```

---

## 11. Business Rules & Edge Cases

### 11.1 Doctor Visibility Rules

A doctor appears in patient search results ONLY when ALL of the following are true:
1. `is_approved = true`
2. `is_active = true` (at least one active clinic)
3. NOT currently on vacation (`vacation_start ≤ now ≤ vacation_end` → hidden)
4. Has at least one matching available_slot day in the next 7 days

### 11.2 Search Fallback Chain

For each specialization the LLM recommends:
1. Find doctors in patient's **pincode** first
2. If empty → find doctors in patient's **city**
3. If empty → find doctors with matching specialization in **all India**
4. If still empty → show "No {spec} available" → back to menu

Members (`is_member = true`) always sort first within each fallback level.

### 11.3 Doctor Discovery Deduplication

If a doctor has multiple specializations or multiple clinics that match, they appear only ONCE in the carousel. The first match wins.

Max doctors shown: 5 per carousel section.

### 11.4 Duplicate Booking Prevention

Before creating an appointment, check:
```sql
SELECT id FROM appointments
WHERE patient_id = ? AND doctor_id = ? AND slot_day = ?
AND status IN ('pending', 'confirmed')
```

If match found → reject with duplicate message. Patient stays in `AWAITING_SLOT_FLOW` to pick a different date.

### 11.5 Rejected Slot Filtering

When a doctor rejects a specific slot_window:
- `context.rejected_slots[doctor_id] = slot_window`
- Future slot pickers for that doctor exclude this window
- In the webapp, store as session variable: `rejectedSlots: { [doctorId]: slotWindow }`

### 11.6 Session Timeout

Any conversation inactive for **3 hours** resets to IDLE. Open analytics sessions are closed with `end_reason = "timeout"`.

In webapp: implement via JWT expiry or session middleware.

### 11.7 Message Deduplication

Each WhatsApp message has a unique `message_id`. The system records this in a DB table before processing. Duplicate deliveries (Meta retries) are dropped.

Webapp equivalent: use idempotency keys on POST requests.

### 11.8 Stale Message Filtering

Messages older than **5 minutes** are dropped (prevents old queued commands from replaying after downtime).

Webapp equivalent: Not needed for HTTP-based interactions.

### 11.9 Admin Reset Numbers

The following phone numbers can send `/reset` to purge all their data (dev/debug):
```python
ADMIN_RESET_NUMBERS = {
    "919300499439", "919893767466", "918827673982", "919131494753"
}
```

### 11.10 appointment_time Computation (IST)

When a doctor confirms an appointment:
```python
# Given: slot_day = "Monday", slot_window = "9AM - 1PM"
# 1. Parse start hour from slot_window ("9AM" → 9)
# 2. Find the next occurrence of slot_day (weekday) from now in IST
# 3. If today IS that weekday but start hour has already passed → add 7 days
# 4. Set appointment_time to that date at start_hour:00:00 IST
# 5. Store as UTC in DB (convert IST → UTC: subtract 5h30m)
```

### 11.11 Per-User Serialization

The original uses `asyncio.Lock` per user number to prevent race conditions when two messages arrive nearly simultaneously. In the webapp, this is less of an issue with request-response APIs, but implement optimistic locking or row-level DB locks for critical operations (appointment creation, status updates).

---

## 12. Environment Variables

```bash
# Meta / WhatsApp (NOT needed in webapp)
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_FLOW_SIGNING_SECRET=
WHATSAPP_PRIVATE_KEY=       # RSA private key PEM string for flow decryption

# WhatsApp Flow IDs (NOT needed in webapp)
WHATSAPP_PATIENT_FLOW_ID=
WHATSAPP_PATIENT_FLOW_ID_HINDI=
WHATSAPP_PATIENT_FLOW_ID_ENGLISH=
WHATSAPP_UPDATE_PATIENT_FLOW_ID=
WHATSAPP_SLOT_FLOW_ID=
WHATSAPP_DOCTOR_FLOW_ID=
WHATSAPP_ADD_CLINIC_FLOW_ID=
WHATSAPP_VACATION_FLOW_ID=
WHATSAPP_DOCTOR_APPOINTMENTS_FLOW_ID=
WHATSAPP_DOCTOR_PROFILE_FLOW_ID=
WHATSAPP_UPDATE_PROFILE_FLOW_ID=

# Pre-approved Message Template Names (NOT needed in webapp)
WHATSAPP_APPT_NOTIFICATION_TEMPLATE=appointment_request
WHATSAPP_REMINDER_PATIENT_TEMPLATE=appointment_reminder_patient
WHATSAPP_REMINDER_DOCTOR_TEMPLATE=appointment_reminder_doctor

# Supabase (KEEP)
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=doctor-photos

# LiteLLM / Gemini (KEEP)
GEMINI_API_KEY=

# Internal (KEEP — rename to better reflect purpose)
INTERNAL_SECRET=            # 32-char random token for cron/admin auth

# App
PORT=8000
ENVIRONMENT=dev             # "dev" or "prod" — loads .env.dev or .env.prod
```

**Webapp additions needed:**
```bash
JWT_SECRET=                 # For patient/doctor authentication
JWT_EXPIRY_HOURS=24
SMTP_HOST=                  # For email notifications
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMS_API_KEY=                # For SMS reminders (e.g. Twilio, MSG91)
FRONTEND_URL=               # For CORS and deep links
```

---

## 13. Reminder System

### 13.1 Trigger Condition

```sql
SELECT a.*, p.whatsapp_number AS patient_number, p.name AS patient_name, p.language,
       d.whatsapp_number AS doctor_number, d.name AS doctor_name
FROM appointments a
JOIN patients p ON a.patient_id = p.id
JOIN doctors d ON a.doctor_id = d.id
WHERE a.status = 'confirmed'
  AND a.reminder_sent = false
  AND a.appointment_time BETWEEN now() + interval '1.5 hours' AND now() + interval '2.5 hours'
```

### 13.2 Process

```
For each appointment in the 2-hour window:
    1. Format appointment time as human-readable IST string
    2. Send reminder to patient (language-aware) via template or fallback text
    3. Send reminder to doctor (always English) via template or fallback text
    4. Update: appointment.reminder_sent = true
    5. Log: reminder_sent
```

### 13.3 Schedule

Runs every 5 minutes via Supabase pg_cron:
```sql
SELECT cron.schedule('send-reminders', '*/5 * * * *',
  'SELECT net.http_post(
    url := ''https://your-app.com/internal/send-reminders'',
    headers := jsonb_build_object(''Authorization'', ''Bearer '' || current_setting(''app.internal_secret'')),
    body := ''{}''
  )'
);
```

In webapp: replace with a cron job (e.g. GitHub Actions, Railway cron, or an in-process scheduler).

---

## 14. Admin Operations

### 14.1 Approve Doctor

```
POST /internal/approve-doctor?doctor_id={id}&approved=true&notify=true
```

- Sets `doctors.is_approved = true/false`
- If `notify=true`: sends approval/rejection message to doctor's WhatsApp (webapp: email/SMS)
- Approval message: "✅ *Great news!* Your Sympto profile has been approved..."
- Rejection message: "We're sorry — your Sympto application could not be approved at this time..."

### 14.2 Set Premium Membership

```
POST /internal/set-member?doctor_id={id}&is_member=true&notify=true
```

- Sets `doctors.is_member = true/false`
- Member doctors sort first in all search results
- Grant message: "🌟 *Welcome to Sympto Premium!*..."
- Revoke message: "Your Sympto Premium membership has ended..."

### 14.3 List Pending Doctors

```
GET /internal/pending-doctors
→ Returns all doctors with is_approved=false, ordered by registered_at ASC
```

---

## 15. Activity Logging Events

All events logged to `activity_logs` table with `event` (snake_case), `whatsapp_number`, `role`, and `detail` (JSONB).

| Event | Role | Detail Keys |
|---|---|---|
| `new_user_first_contact` | patient | — |
| `patient_entered_menu` | patient | `name` |
| `patient_registered` | patient | `name`, `age`, `gender`, `city`, `language` |
| `patient_profile_updated` | patient | `name`, `city` |
| `booking_session_started` | patient | `session_id` |
| `session_abandoned` | patient | `session_id`, `reason` |
| `symptoms_submitted` | patient | `symptoms`, `session_id` |
| `llm_analysis_complete` | patient | `specializations`, `urgency`, `is_emergency`, `has_followup`, `session_id` |
| `llm_unavailable` | patient | `stage` |
| `emergency_detected` | patient | `symptoms` |
| `browse_specialty_selected` | patient | `specialization`, `session_id` |
| `doctors_shown` | patient | `specializations`, `count`, `doctor_ids`, `session_id` |
| `no_doctors_found` | patient | `specializations`, `session_id` |
| `appointment_created` | patient | `appointment_id`, `doctor_id`, `slot_day`, `slot_window`, `urgency`, `session_id` |
| `duplicate_booking_blocked` | patient | `doctor_id`, `doctor_name`, `slot_day`, `session_id` |
| `appointment_confirmed` | patient | `doctor_name`, `slot_day`, `slot_window`, `clinic_name`, `city`, `session_id` |
| `appointment_rejected_by_doctor` | patient | `doctor_name`, `doctor_id`, `appointment_id`, `slot_window`, `session_id` |
| `doctor_registration_started` | doctor | — |
| `doctor_registration_attempted_duplicate` | doctor | `name` |
| `doctor_registration_complete` | doctor | `name`, `specialization`, `city`, `clinic_name` |
| `doctor_availability_update_started` | doctor | `name` |
| `doctor_clinic_added` | doctor | `clinic_name`, `city` |
| `doctor_availability_updated_single` | doctor | `clinic_id` |
| `doctor_availability_updated_all` | doctor | — |
| `doctor_upcoming_appointments_viewed` | doctor | `doctor_id`, `pending`, `confirmed`, `cancelled` |
| `doctor_confirmed_appointment` | doctor | `appointment_id`, `patient_number`, `patient_name`, `slot_day`, `slot_window`, `appointment_time` |
| `doctor_rejected_appointment` | doctor | `appointment_id`, `patient_number`, `patient_name`, `slot_day`, `slot_window` |
| `message_received` | patient/doctor | `type`, `content`, `state` |
| `session_timeout` | patient | `previous_state`, `timeout_hours` |
| `conversation_purged` | patient/doctor | `previous_state`, `trigger` |
| `reminder_sent` | system | `appointment_id`, `patient_number`, `doctor_number`, `appointment_time` |
| `reminder_failed` | system | `appointment_id`, `error` |

---

## 16. Complete Conversation Context Object

The `conversations.context` JSONB stores all session variables. Here is the complete schema:

```json
{
  "preferred_language": "english | hindi | hinglish | null",
  "is_language_change": "bool (set during language change flow)",
  "session_id": "UUID (analytics session, created on 'book_appointment' tap)",
  
  "symptoms": "string (original symptom text)",
  "followup_turns": [
    {"role": "question", "content": "LLM's follow-up question"},
    {"role": "answer", "content": "Patient's answer"},
    ...
  ],
  "llm_result": {
    "specializations": ["Cardiologist"],
    "display_names": ["Cardiologist"],
    "confidence_scores": [85],
    "summary": "Patient presents with chest pain and shortness of breath.",
    "urgency": "urgent",
    "is_emergency": false,
    "followup_question": null,
    "was_force_concluded": false
  },
  
  "doctors_shown": ["uuid1", "uuid2", ...],
  "excluded_doctor_ids": ["uuid3"],
  "browse_specialty": "cardiologist (set when browsing, not symptom analysis)",
  
  "selected_doctor_id": "UUID",
  "selected_clinic_id": "UUID | null",
  "pending_slot_date": "YYYY-MM-DD",
  "rejected_slots": {
    "doctor_uuid": "9am - 1pm"
  },
  
  "appointment_id": "UUID",
  "wait_replied": "bool (true after first message in CONFIRMING state)",
  "cancel_confirm_pending": "bool (true when cancel confirmation shown)",
  "cancel_target_id": "UUID (appointment to cancel, in VIEWING_APPOINTMENTS flow)",
  
  "browse_page": "int (current page in specialty picker)",
  
  "clinic_flow_session": {
    "clinic_name": "string",
    "state": "string",
    "city": "string",
    "pincode": "string",
    "address": "string",
    "maps": "string",
    "configured_slots": {
      "monday": [["09:00 AM", "01:00 PM"]],
      "wednesday": [["05:00 PM", "09:00 PM"]]
    },
    "selected_days": ["monday", "wednesday"],
    "pending_days": ["wednesday"],
    "existing_slots": []
  },
  
  "reg_flow_session": {
    "name": "string",
    "registration_number": "string",
    "year_register": "string",
    "specialization": "string",
    "clinic_name": "string",
    "address": "string",
    "state": "string",
    "city": "string",
    "pincode": "string",
    "maps": "string",
    "configured_slots": {},
    "selected_days": [],
    "pending_days": []
  },
  
  "add_clinic_mode": "new | update_single | update_all",
  "update_clinic_id": "UUID (for update_single mode)",
  "clinic_prefill_days": ["monday", "wednesday"]
}
```

---

## 17. Doctor Notification Template (Appointment Request)

The `appointment_request` WhatsApp template message sent to the doctor when a patient books a slot.

**WhatsApp template payload structure:**
```json
{
  "messaging_product": "whatsapp",
  "to": "<doctor_phone>",
  "type": "template",
  "template": {
    "name": "appointment_request",
    "language": {"code": "en"},
    "components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": "Patient Name"},
          {"type": "text", "text": "25"},
          {"type": "text", "text": "Female"},
          {"type": "text", "text": "Symptoms summary text"},
          {"type": "text", "text": "urgent"},
          {"type": "text", "text": "Monday"},
          {"type": "text", "text": "9AM - 1PM"}
        ]
      },
      {
        "type": "button",
        "sub_type": "quick_reply",
        "index": 0,
        "parameters": [{"type": "payload", "payload": "confirm_appt_<appointment_id>"}]
      },
      {
        "type": "button",
        "sub_type": "quick_reply",
        "index": 1,
        "parameters": [{"type": "payload", "payload": "reject_appt_<appointment_id>"}]
      }
    ]
  }
}
```

**Web API equivalent:** Send an email or push notification to the doctor with a confirm/reject link:
```
Confirm: POST /api/doctor/confirm?appointment_id={id}&token={jwt}
Reject:  POST /api/doctor/reject?appointment_id={id}&token={jwt}
```

**Notification email body:**
```
New Appointment Request

Patient: {patient_name}
Age: {patient_age} | Gender: {patient_gender}
Symptoms: {symptoms_summary}
Urgency: {urgency}
Requested slot: {slot_day}, {slot_window}

[Confirm Appointment]  [Reject Appointment]
```

---

## 18. Slot & Availability Data Model

### 18.1 Available Slots Format (DB Storage)

Stored as JSONB array in `clinics.available_slots`:

```json
[
  {"day": "monday",    "window": "9am - 1pm"},
  {"day": "monday",    "window": "5pm - 9pm"},
  {"day": "wednesday", "window": "9am - 1pm"},
  {"day": "friday",    "window": "1pm - 5pm"}
]
```

### 18.2 Day Mapping

| Abbreviation (Flow) | Full Name (DB) | Display | Weekday Index |
|---|---|---|---|
| Mon | monday | Monday | 0 |
| Tue | tuesday | Tuesday | 1 |
| Wed | wednesday | Wednesday | 2 |
| Thu | thursday | Thursday | 3 |
| Fri | friday | Friday | 4 |
| Sat | saturday | Saturday | 5 |
| Sun | sunday | Sunday | 6 |

**Calendar display (availability string):** Abbreviated days joined by middle dot:
- `"Mo·Th·Fr"` means available Monday, Thursday, Friday

### 18.3 Window Mapping

| DB Value (available_slots) | Slot ID | Display Label | Short Label |
|---|---|---|---|
| `"9am - 1pm"` | `morning` | `Morning (9–1 PM)` | `Morning` |
| `"1pm - 5pm"` | `afternoon` | `Afternoon (1–5 PM)` | `Afternoon` |
| `"5pm - 9pm"` | `evening` | `Evening (5–9 PM)` | `Evening` |

**Appointment stored in DB** (normalized, title-case):
- `slot_window`: `"9AM - 1PM"`, `"1PM - 5PM"`, `"5PM - 9PM"`
- `slot_day`: `"Monday"`, `"Tuesday"`, ..., `"Sunday"` (title-case)

### 18.4 Date Picker Logic (Next 7 Days)

```python
today = date.today()
for i in range(1, 8):              # tomorrow through +7 days (never today)
    d = today + timedelta(days=i)
    day_name = d.strftime("%A").lower()  # "monday"
    windows = windows_by_day.get(day_name, [])
    if windows:
        # Include this day in the picker
        # Display: "Monday, Apr 3"
        # Description: "Morning, Evening"
```

### 18.5 Slot Parse Hour (for appointment_time computation)

```python
def _parse_hour(window: str) -> int:
    # "9AM - 1PM" → 9
    # "9am - 1pm" → 9
    # "1PM - 5PM" → 13
    # "5PM - 9PM" → 17
    start = window.split("-")[0].strip().upper()
    if "AM" in start:
        h = int(start.replace("AM", "").strip())
        return 0 if h == 12 else h
    elif "PM" in start:
        h = int(start.replace("PM", "").strip())
        return h if h == 12 else h + 12
```

---

## Appendix A: Webhook Message Routing Priority

In the WhatsApp bot, all incoming messages are routed as follows. In the webapp, this maps to which API endpoint handles which action:

```
Priority 1: Doctor action buttons (confirm_appt_*, reject_appt_*)
  → Handle immediately regardless of role or state

Priority 2: WhatsApp Flow submissions (nfm_reply)
  → Route to doctor handler if flow_token starts with doctor_registration / add_clinic / vacation / etc.
  → Route to patient handler for patient_profile flows

Priority 3: Doctor registration trigger text (exact match)
  → Force to doctor handler regardless of current role

Priority 4: Role-based fallthrough
  → role == "doctor" → doctor handler
  → else → patient handler
```

---

## Appendix B: Flow Token Format

Flow tokens are used to route decrypted flow submissions to the correct user. Format:

```
patient_profile_{wa_number}_{hex8}          → patient profile form
doctor_registration_{wa_number}_{hex8}      → doctor registration
add_clinic_{wa_number}_{hex8}               → add/update clinic
update_profile_{wa_number}_{hex8}           → doctor profile update
vacation_{wa_number}_{hex8}                 → vacation mode
doctor_appointments_{wa_number}_{hex8}      → doctor appointments flow
slot_picker_{wa_number}_{hex8}              → slot picker (patient)
```

In the webapp, these tokens are replaced by JWT session tokens or standard API authentication.

---

## Appendix C: Multi-Language Flow ID Selection

The bot selects different WhatsApp Flow IDs based on the patient's language:

```python
def _get_flow_id(base, alt_hindi, alt_english, lang):
    if lang == "hindi" and alt_hindi:
        return alt_hindi
    if lang == "english" and alt_english:
        return alt_english
    return base  # hinglish (default)
```

Webapp equivalent: Use i18n locale routing or pass `lang` query parameter to form pages.

---

## Appendix D: Appointment Reminder Query (Exact)

```sql
SELECT 
    a.*,
    p.whatsapp_number AS patient_number,
    p.name AS patient_name,
    p.language AS patient_lang,
    d.whatsapp_number AS doctor_number,
    d.name AS doctor_name
FROM appointments a
JOIN patients p ON a.patient_id = p.id
JOIN doctors d ON a.doctor_id = d.id
WHERE a.status = 'confirmed'
  AND a.reminder_sent = false
  AND a.appointment_time >= NOW() + INTERVAL '90 minutes'
  AND a.appointment_time <= NOW() + INTERVAL '150 minutes';
```

---

## Appendix E: Doctor Search Query Logic

```python
async def find_doctors(specialization, pincode, city, exclude_ids):
    """3-level fallback search. Returns (doctors, fallback_level)."""
    
    # Level 1: By pincode
    result = query_where(
        specialization=specialization,
        pincode=pincode,
        exclude_ids=exclude_ids,
        is_approved=True,
        not_on_vacation=True,
        order_by=["is_member DESC", "registered_at ASC"],
        limit=5
    )
    if result: return result, "pincode"
    
    # Level 2: By city
    result = query_where(
        specialization=specialization,
        city=city,
        exclude_ids=exclude_ids,
        is_approved=True,
        not_on_vacation=True,
        order_by=["is_member DESC", "registered_at ASC"],
        limit=5
    )
    if result: return result, "city"
    
    # Level 3: All India
    result = query_where(
        specialization=specialization,
        exclude_ids=exclude_ids,
        is_approved=True,
        not_on_vacation=True,
        order_by=["is_member DESC", "registered_at ASC"],
        limit=5
    )
    return result, "all"

# Vacation check:
# NOT (vacation_start <= now AND vacation_end >= now)
```

---

## Appendix F: WhatsApp API Message Types

For reference (not needed in webapp), the WhatsApp Cloud API message types used:

| Type | WA API Type | Max Items |
|---|---|---|
| Plain text | `text` | — |
| Quick reply buttons | `interactive/button` | 3 buttons |
| List (menu) | `interactive/list` | 10 rows total across sections |
| Flow trigger | `interactive/flow` | 1 flow |
| Carousel (doctor cards) | `interactive/product_list` | 5 sections |
| Template | `template` | — |
| Mark as read | `status: read` | — |

**Row/button character limits:**
- Button title: 20 chars max
- List row title: 24 chars max
- List row description: 72 chars max

---

*End of Sympto Web App Migration Specification*

*Document generated from source code analysis of FindMyDoctorWhatsApp-main as of June 2026.*
*Every state, message, rule, and data structure in this document is directly derived from the running production codebase.*
