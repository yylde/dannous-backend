-- Migration: Add queue_tasks table for queue persistence
-- Description: Adds queue_tasks table to persist Ollama queue tasks across server restarts
-- Created: 2025-11-09

CREATE TABLE IF NOT EXISTS queue_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type TEXT NOT NULL,
    book_id UUID,
    chapter_id UUID,
    priority INTEGER NOT NULL,
    args JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_queue_tasks_priority ON queue_tasks(priority, created_at);
CREATE INDEX IF NOT EXISTS idx_queue_tasks_book_id ON queue_tasks(book_id);
CREATE INDEX IF NOT EXISTS idx_queue_tasks_chapter_id ON queue_tasks(chapter_id);

COMMENT ON TABLE queue_tasks IS 'Stores pending Ollama queue tasks for persistence across server restarts';
COMMENT ON COLUMN queue_tasks.task_type IS 'Type of task: description, tags, questions';
COMMENT ON COLUMN queue_tasks.args IS 'JSONB object containing task arguments and function details';
