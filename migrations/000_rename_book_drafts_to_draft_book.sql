-- Migration: Rename book_drafts table to draft_book
-- Description: Renames the existing book_drafts table and all its indexes to use the new draft_book naming convention
-- Created: 2025-10-19
-- IMPORTANT: Run this migration BEFORE running other migrations if you have an existing book_drafts table

-- Rename the main table
ALTER TABLE IF EXISTS book_drafts RENAME TO draft_book;

-- Rename indexes to match new table name
ALTER INDEX IF EXISTS idx_book_drafts_gutenberg_id RENAME TO idx_draft_book_gutenberg_id;
ALTER INDEX IF EXISTS idx_book_drafts_is_completed RENAME TO idx_draft_book_is_completed;
ALTER INDEX IF EXISTS idx_book_drafts_tags RENAME TO idx_draft_book_tags;

-- Note: Foreign key constraints are automatically updated when the table is renamed
-- The foreign keys in draft_chapters and draft_questions will now reference draft_book(id)
