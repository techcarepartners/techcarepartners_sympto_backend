-- Run this in the Supabase SQL Editor
-- Creates the doctor_vacations table for multiple vacation ranges per doctor

CREATE TABLE IF NOT EXISTS doctor_vacations (
  id            UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  doctor_id     UUID        NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
  vacation_start DATE       NOT NULL,
  vacation_end   DATE       NOT NULL,
  vacation_reason TEXT      NOT NULL DEFAULT 'On Vacation',
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT valid_range CHECK (vacation_end >= vacation_start)
);

CREATE INDEX IF NOT EXISTS idx_doctor_vacations_doctor_id
  ON doctor_vacations(doctor_id);

-- Disable RLS (app uses service role key)
ALTER TABLE doctor_vacations DISABLE ROW LEVEL SECURITY;
