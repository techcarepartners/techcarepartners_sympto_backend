-- ============================================================
-- Sympto Healthcare Platform — Complete Database Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- 1. PATIENTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number   text        UNIQUE NOT NULL,
    name              text        NOT NULL DEFAULT '',
    age               integer     NOT NULL DEFAULT 0,
    gender            text        NOT NULL DEFAULT 'other',
    state             text        NOT NULL DEFAULT '',
    city              text        NOT NULL DEFAULT '',
    pincode           text        NOT NULL DEFAULT '000000',
    language          text        NOT NULL DEFAULT 'english',
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- 2. DOCTORS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS doctors (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number     text        UNIQUE NOT NULL,
    name                text        NOT NULL DEFAULT '',
    specialization      text        NOT NULL DEFAULT '',
    registration_number text        NOT NULL DEFAULT '',
    year_register       text        NOT NULL DEFAULT '',
    is_approved         boolean     NOT NULL DEFAULT false,
    is_member           boolean     NOT NULL DEFAULT false,
    multi_clinic        boolean     NOT NULL DEFAULT false,
    photo_url           text,
    vacation_start      text,                  -- ISO date string "2025-12-20"
    vacation_end        text,                  -- ISO date string "2025-12-31"
    registered_at       timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- 3. CLINICS
--    Each doctor can have one or more clinics.
--    available_slots is a JSONB array of {day, window} objects, e.g.:
--    [{"day": "monday", "window": "9am - 1pm"}, ...]
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clinics (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       uuid        NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    clinic_name     text        NOT NULL DEFAULT '',
    address         text        NOT NULL DEFAULT '',
    state           text        NOT NULL DEFAULT '',
    city            text        NOT NULL DEFAULT '',
    pincode         text        NOT NULL DEFAULT '',
    maps            text        NOT NULL DEFAULT '',
    available_slots jsonb       NOT NULL DEFAULT '[]',
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- 4. CONVERSATIONS  (patient session / state machine)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  text        UNIQUE NOT NULL,
    role             text        NOT NULL DEFAULT 'patient',
    state            text        NOT NULL DEFAULT 'IDLE',
    context          jsonb       NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- 5. APPOINTMENTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id        uuid        NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id         uuid        NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    clinic_id         uuid        REFERENCES clinics(id) ON DELETE SET NULL,
    slot_day          text        NOT NULL,           -- e.g. "Monday"
    slot_window       text        NOT NULL,           -- e.g. "9AM - 1PM"
    symptoms_summary  text,
    urgency           text        NOT NULL DEFAULT 'routine',
    status            text        NOT NULL DEFAULT 'pending',
    appointment_time  timestamptz,                   -- set on confirmation
    reminder_sent     boolean     NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- 6. ACTIVITY LOGS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activity_logs (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  text,
    role             text        NOT NULL DEFAULT '',
    event            text        NOT NULL,
    detail           jsonb       NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- 7. CONVERSATION SESSIONS  (analytics)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number  text        NOT NULL DEFAULT '',
    context_snapshot jsonb       NOT NULL DEFAULT '{}',
    ended_at         timestamptz,
    final_state      text,
    end_reason       text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- INDEXES  (performance for common query patterns)
-- ============================================================

-- Doctors: fast approval + specialization lookups
CREATE INDEX IF NOT EXISTS idx_doctors_approved       ON doctors(is_approved);
CREATE INDEX IF NOT EXISTS idx_doctors_specialization ON doctors(specialization);
CREATE INDEX IF NOT EXISTS idx_doctors_member         ON doctors(is_member);

-- Clinics: fast location-based search
CREATE INDEX IF NOT EXISTS idx_clinics_doctor_id ON clinics(doctor_id);
CREATE INDEX IF NOT EXISTS idx_clinics_pincode   ON clinics(pincode);
CREATE INDEX IF NOT EXISTS idx_clinics_city      ON clinics(city);
CREATE INDEX IF NOT EXISTS idx_clinics_active    ON clinics(is_active);

-- Appointments: fast patient/doctor lookups + reminder queries
CREATE INDEX IF NOT EXISTS idx_appts_patient_id ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appts_doctor_id  ON appointments(doctor_id);
CREATE INDEX IF NOT EXISTS idx_appts_status     ON appointments(status);
CREATE INDEX IF NOT EXISTS idx_appts_time       ON appointments(appointment_time) WHERE appointment_time IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_appts_reminder   ON appointments(reminder_sent) WHERE status = 'confirmed';

-- Activity logs: time-based queries
CREATE INDEX IF NOT EXISTS idx_logs_event      ON activity_logs(event);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON activity_logs(created_at DESC);

-- ============================================================
-- ROW LEVEL SECURITY
--   The backend uses the SERVICE_ROLE_KEY which bypasses RLS.
--   Disable RLS on all tables so the backend works out of the box.
-- ============================================================
ALTER TABLE patients              DISABLE ROW LEVEL SECURITY;
ALTER TABLE doctors               DISABLE ROW LEVEL SECURITY;
ALTER TABLE clinics               DISABLE ROW LEVEL SECURITY;
ALTER TABLE conversations         DISABLE ROW LEVEL SECURITY;
ALTER TABLE appointments          DISABLE ROW LEVEL SECURITY;
ALTER TABLE activity_logs         DISABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_sessions DISABLE ROW LEVEL SECURITY;

-- ============================================================
-- DONE — 7 tables, indexes, RLS disabled
-- ============================================================
