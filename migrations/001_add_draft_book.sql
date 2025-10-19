-- Migration: Add draft book tracking system
-- Description: Adds tables to track books in progress with async question generation

-- Table for tracking books in progress
CREATE TABLE IF NOT EXISTS draft_books (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gutenberg_id INTEGER,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(300) NOT NULL,
    cover_image_url VARCHAR(500),
    full_text TEXT NOT NULL,
    full_html TEXT,  -- Stores original EPUB HTML for vocabulary tooltip injection
    age_range VARCHAR(20),
    reading_level VARCHAR(20),
    genre VARCHAR(100),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_completed BOOLEAN DEFAULT false
);

-- Table for chapters in draft books
CREATE TABLE IF NOT EXISTS draft_chapters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES draft_books(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title VARCHAR(300) NOT NULL,
    content TEXT NOT NULL,
    html_formatting TEXT,
    word_count INTEGER NOT NULL,
    has_questions BOOLEAN DEFAULT false,
    question_status VARCHAR(20) DEFAULT 'pending', -- pending, generating, ready, error
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(draft_id, chapter_number)
);

-- Table for questions in draft chapters
CREATE TABLE IF NOT EXISTS draft_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES draft_books(id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES draft_chapters(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type VARCHAR(50) NOT NULL DEFAULT 'comprehension',
    difficulty_level VARCHAR(20) DEFAULT 'medium',
    expected_keywords JSONB DEFAULT '[]',
    min_word_count INTEGER DEFAULT 20,
    max_word_count INTEGER DEFAULT 200,
    order_index INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table for vocabulary in draft chapters
CREATE TABLE IF NOT EXISTS draft_vocabulary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES draft_chapters(id) ON DELETE CASCADE,
    word VARCHAR(100) NOT NULL,
    definition TEXT NOT NULL,
    example TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_draft_book_gutenberg_id ON draft_books(gutenberg_id);
CREATE INDEX IF NOT EXISTS idx_draft_book_is_completed ON draft_books(is_completed);
CREATE INDEX IF NOT EXISTS idx_draft_chapters_draft_id ON draft_chapters(draft_id);
CREATE INDEX IF NOT EXISTS idx_draft_chapters_has_questions ON draft_chapters(has_questions);
CREATE INDEX IF NOT EXISTS idx_draft_chapters_status ON draft_chapters(question_status);
CREATE INDEX IF NOT EXISTS idx_draft_questions_chapter_id ON draft_questions(chapter_id);
CREATE INDEX IF NOT EXISTS idx_draft_vocabulary_chapter_id ON draft_vocabulary(chapter_id);
