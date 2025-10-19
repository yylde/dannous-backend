-- Migration: Add tags column to book_drafts
-- Description: Adds JSONB tags column to support AI-extracted genre and grade-level categorization
-- Created: 2025-10-19

-- Add tags column to book_drafts table
ALTER TABLE book_drafts 
ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]';

-- Add index for better performance when filtering by tags
CREATE INDEX IF NOT EXISTS idx_book_drafts_tags ON book_drafts USING GIN (tags);

-- Add comment to document the column
COMMENT ON COLUMN book_drafts.tags IS 'AI-extracted tags for genre and grade-level categorization (e.g., ["adventure", "fantasy", "grades-4-6"])';
