-- Migration: Add last_marker_position column to draft_books table
-- Purpose: Store the position of the last chapter marker placed by user
-- Date: 2025-10-26

-- Add last_marker_position column to store marker position data
ALTER TABLE draft_books
ADD COLUMN IF NOT EXISTS last_marker_position JSONB DEFAULT NULL;

-- Add comment to describe the column
COMMENT ON COLUMN draft_books.last_marker_position IS 'Stores the position of the last chapter marker placed by user (x, y coordinates, paragraph index, timestamp)';
