-- Migration 013: Add uniqueness constraint for queue tasks
-- This prevents duplicate tasks with the same grade_level for a chapter

-- Drop existing index if it exists
DROP INDEX IF EXISTS idx_queue_tasks_unique_grade;

-- Create unique partial index for question tasks with grade_level
-- This ensures only one queued task exists per (task_type, book_id, chapter_id, grade_level)
CREATE UNIQUE INDEX idx_queue_tasks_unique_grade
ON queue_tasks (task_type, book_id, chapter_id, (payload->>'grade_level'))
WHERE status = 'queued' AND task_type = 'questions';

-- For book-level tasks (tags, descriptions), ensure only one queued task exists
CREATE UNIQUE INDEX idx_queue_tasks_unique_book
ON queue_tasks (task_type, book_id)
WHERE status = 'queued' AND chapter_id IS NULL;
