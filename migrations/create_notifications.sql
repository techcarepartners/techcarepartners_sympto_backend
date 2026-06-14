-- Run in Supabase SQL Editor
CREATE TABLE IF NOT EXISTS notifications (
  id             UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  recipient_role TEXT        NOT NULL CHECK (recipient_role IN ('patient','doctor','admin')),
  recipient_id   UUID,       -- NULL for admin (role-wide)
  type           TEXT        NOT NULL,
  title          TEXT        NOT NULL,
  body           TEXT        NOT NULL,
  is_read        BOOLEAN     DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  metadata       JSONB       DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient
  ON notifications(recipient_role, recipient_id, is_read, created_at DESC);

ALTER TABLE notifications DISABLE ROW LEVEL SECURITY;
