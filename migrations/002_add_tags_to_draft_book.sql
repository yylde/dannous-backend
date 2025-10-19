-- Migration: Add tags column to draft_book
-- Description: Adds JSONB tags column to support AI-extracted genre and grade-level categorization
-- Created: 2025-10-19

-- Add tags column to draft_book table
ALTER TABLE draft_book 
ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]';

-- Add index for better performance when filtering by tags
CREATE INDEX IF NOT EXISTS idx_draft_book_tags ON draft_book USING GIN (tags);

-- Add comment to document the column
COMMENT ON COLUMN draft_book.tags IS 'AI-extracted tags for genre and grade-level categorization (e.g., ["adventure", "fantasy", "grades-4-6"])';
