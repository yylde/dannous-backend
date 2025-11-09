-- Migration: Add granular grade-level status tracking for question generation
-- Description: Tracks status for each grade level within a chapter independently

CREATE TABLE IF NOT EXISTS draft_chapter_grade_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES draft_chapters(id) ON DELETE CASCADE,
    grade_level VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    queue_task_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_chapter_grade UNIQUE (chapter_id, grade_level),
    CONSTRAINT valid_status CHECK (status IN ('pending', 'queued', 'generating', 'ready', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_grade_status_chapter ON draft_chapter_grade_status(chapter_id);
CREATE INDEX IF NOT EXISTS idx_grade_status_status ON draft_chapter_grade_status(status);
CREATE INDEX IF NOT EXISTS idx_grade_status_queue_task ON draft_chapter_grade_status(queue_task_id) WHERE queue_task_id IS NOT NULL;

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_grade_status_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_grade_status_timestamp
    BEFORE UPDATE ON draft_chapter_grade_status
    FOR EACH ROW
    EXECUTE FUNCTION update_grade_status_timestamp();
