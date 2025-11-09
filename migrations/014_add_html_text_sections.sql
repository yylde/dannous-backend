-- Migration 014: Add html_sections and text_sections to draft_books
-- These store the EPUB content as arrays to preserve formatting (br tags, nbsp, styles, etc.)

ALTER TABLE draft_books
ADD COLUMN html_sections JSONB DEFAULT '[]'::jsonb,
ADD COLUMN text_sections JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN draft_books.html_sections IS 'Array of HTML sections from EPUB with formatting preserved';
COMMENT ON COLUMN draft_books.text_sections IS 'Array of plain text sections from EPUB';
