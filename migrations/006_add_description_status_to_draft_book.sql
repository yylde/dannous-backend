-- Migration: Add description_status column to draft_books
-- Description: Adds description_status column to track async description generation for books
-- Created: 2025-10-27

-- Add description_status column to draft_books table
ALTER TABLE draft_books 
ADD COLUMN IF NOT EXISTS description_status VARCHAR(20) DEFAULT 'pending';

-- Add index for better performance when filtering by description status
CREATE INDEX IF NOT EXISTS idx_draft_book_description_status ON draft_books(description_status);

-- Add comment to document the column
COMMENT ON COLUMN draft_books.description_status IS 'Status of async description generation: pending, generating, ready, error';
