-- Migration: Add tag_status column to draft_books
-- Description: Adds tag_status column to track async tag generation for books
-- Created: 2025-10-19

-- Add tag_status column to draft_books table
ALTER TABLE draft_books 
ADD COLUMN IF NOT EXISTS tag_status VARCHAR(20) DEFAULT 'pending';

-- Add index for better performance when filtering by tag status
CREATE INDEX IF NOT EXISTS idx_draft_book_tag_status ON draft_books(tag_status);

-- Add comment to document the column
COMMENT ON COLUMN draft_books.tag_status IS 'Status of async tag generation: pending, generating, ready, error';
