-- Migration: Add tags column to draft_books
-- Description: Adds JSONB tags column to support AI-extracted genre and grade-level categorization
-- Created: 2025-10-19

-- Add tags column to draft_books table
ALTER TABLE draft_books 
ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]';

-- Add index for better performance when filtering by tags
CREATE INDEX IF NOT EXISTS idx_draft_book_tags ON draft_books USING GIN (tags);

-- Add comment to document the column
COMMENT ON COLUMN draft_books.tags IS 'AI-extracted tags for genre and grade-level categorization (e.g., ["adventure", "fantasy", "grades-4-6"])';
