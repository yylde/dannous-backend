-- Database schema for kids reading platform

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Books table
CREATE TABLE IF NOT EXISTS books (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    author VARCHAR(300) NOT NULL,
    description TEXT,
    age_range VARCHAR(20) NOT NULL,
    reading_level VARCHAR(20) NOT NULL,
    genre VARCHAR(100),
    total_chapters INTEGER NOT NULL,
    estimated_reading_time_minutes INTEGER,
    cover_image_url VARCHAR(500),
    isbn VARCHAR(20),
    publication_year INTEGER,
    is_active BOOLEAN DEFAULT true,
    content_rating VARCHAR(20),
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Chapters table
CREATE TABLE IF NOT EXISTS chapters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title VARCHAR(300) NOT NULL,
    content TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    estimated_reading_time_minutes INTEGER NOT NULL,
    vocabulary_words JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(book_id, chapter_number)
);

-- Questions table
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type VARCHAR(50) NOT NULL DEFAULT 'comprehension',
    difficulty_level VARCHAR(20) DEFAULT 'medium',
    expected_keywords JSONB DEFAULT '[]',
    min_word_count INTEGER DEFAULT 20,
    max_word_count INTEGER DEFAULT 200,
    order_index INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for better performance
CREATE INDEX IF NOT EXISTS idx_chapters_book_id ON chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_questions_chapter_id ON questions(chapter_id);
CREATE INDEX IF NOT EXISTS idx_questions_book_id ON questions(book_id);
