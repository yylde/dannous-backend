ALTER TABLE draft_books ADD COLUMN IF NOT EXISTS content_flags JSONB DEFAULT '[]'::jsonb;
