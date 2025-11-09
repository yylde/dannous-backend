-- Migration: Rebuild queue system from scratch
-- Description: Drop old queue tables and create clean queue_tasks table with proper constraints
-- Created: 2025-11-09

-- Drop old queue tables
DROP TABLE IF EXISTS queue_tasks CASCADE;
DROP TABLE IF EXISTS draft_chapter_grade_status CASCADE;

-- Create new queue_tasks table
CREATE TABLE queue_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type VARCHAR(50) NOT NULL,
    priority INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    book_id UUID NOT NULL,
    chapter_id UUID,
    payload JSONB,
    attempts INTEGER DEFAULT 0,
    locked_at TIMESTAMP,
    timeout_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    CONSTRAINT fk_book FOREIGN KEY (book_id) REFERENCES draft_books(id) ON DELETE CASCADE,
    CONSTRAINT fk_chapter FOREIGN KEY (chapter_id) REFERENCES draft_chapters(id) ON DELETE CASCADE,
    
    CHECK (status IN ('queued', 'processing', 'ready', 'error')),
    CHECK (priority IN (1, 2, 3)),
    CHECK (task_type IN ('tags', 'descriptions', 'questions'))
);

-- Indexes for performance
CREATE INDEX idx_queue_status_priority ON queue_tasks(status, priority, created_at) WHERE status IN ('queued', 'processing');
CREATE INDEX idx_queue_book_chapter ON queue_tasks(book_id, chapter_id);
CREATE INDEX idx_queue_timeout ON queue_tasks(timeout_at) WHERE status = 'processing';

-- Comments
COMMENT ON TABLE queue_tasks IS 'Queue system for async Ollama tasks (tags, descriptions, questions)';
COMMENT ON COLUMN queue_tasks.task_type IS 'Type: tags, descriptions, questions';
COMMENT ON COLUMN queue_tasks.priority IS '1=high (tags), 2=medium (descriptions), 3=low (questions)';
COMMENT ON COLUMN queue_tasks.status IS 'Status: queued, processing, ready, error';
COMMENT ON COLUMN queue_tasks.payload IS 'JSON payload with task parameters';
COMMENT ON COLUMN queue_tasks.timeout_at IS 'Task timeout timestamp (15 minutes from start)';
