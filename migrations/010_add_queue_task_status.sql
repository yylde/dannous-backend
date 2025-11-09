-- Migration: Add status tracking to queue_tasks
-- Description: Adds status column to track task lifecycle (pending, processing, completed, failed)
-- Created: 2025-11-09

ALTER TABLE queue_tasks ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS idx_queue_tasks_status ON queue_tasks(status);

COMMENT ON COLUMN queue_tasks.status IS 'Task status: pending, processing, completed, failed';
