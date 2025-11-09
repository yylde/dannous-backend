-- Migration: Deprecate old status fields
-- Description: Remove status columns from draft tables as status is now calculated dynamically
-- Created: 2025-11-09

-- Drop status columns from draft_books
ALTER TABLE draft_books DROP COLUMN IF EXISTS tag_status;
ALTER TABLE draft_books DROP COLUMN IF EXISTS description_status;

-- Drop status columns from draft_chapters
ALTER TABLE draft_chapters DROP COLUMN IF EXISTS question_status;
ALTER TABLE draft_chapters DROP COLUMN IF EXISTS has_questions;
