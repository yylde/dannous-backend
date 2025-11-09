-- Migration: Add cascade deletion for queue tasks
-- Description: Adds foreign key constraint with ON DELETE CASCADE for queue_tasks.chapter_id -> draft_chapters.id
-- Created: 2025-11-09

-- Drop existing constraint if it exists and recreate with CASCADE
ALTER TABLE queue_tasks DROP CONSTRAINT IF EXISTS queue_tasks_chapter_id_fkey;
ALTER TABLE queue_tasks ADD CONSTRAINT queue_tasks_chapter_id_fkey 
  FOREIGN KEY (chapter_id) REFERENCES draft_chapters(id) ON DELETE CASCADE;

COMMENT ON CONSTRAINT queue_tasks_chapter_id_fkey ON queue_tasks IS 'Cascade delete queue tasks when chapter is deleted';
