-- Migration: Add grade_level column to draft_questions
-- Description: Adds grade_level column to track which grade each question targets
-- Created: 2025-10-19

-- Add grade_level column to draft_questions table
ALTER TABLE draft_questions 
ADD COLUMN IF NOT EXISTS grade_level VARCHAR(20);

-- Add index for better performance when filtering by grade level
CREATE INDEX IF NOT EXISTS idx_draft_questions_grade_level ON draft_questions(grade_level);

-- Add comment to document the column
COMMENT ON COLUMN draft_questions.grade_level IS 'Target grade level for this question (e.g., "grade-1", "grade-2", "grade-3")';
