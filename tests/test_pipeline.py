"""Integration tests for EPUB processing pipeline."""

import pytest
from pathlib import Path
from src.text_cleaner import TextCleaner
from src.chapter_splitter import ChapterSplitter
from src.question_generator import QuestionGenerator
from src.database import DatabaseManager


class TestTextCleaner:
    """Test text cleaning functionality."""
    
    def test_removes_gutenberg_header(self):
        """Test removal of Gutenberg header."""
        text = """
        Some preamble text.
        
        *** START OF THE PROJECT GUTENBERG EBOOK ALICE'S ADVENTURES IN WONDERLAND ***
        
        CHAPTER I
        Down the Rabbit-Hole
        
        Alice was beginning to get very tired...
        """
        
        cleaner = TextCleaner()
        cleaned = cleaner.clean(text)
        
        assert "START OF THE PROJECT GUTENBERG" not in cleaned
        assert "CHAPTER I" in cleaned
        assert "Alice was beginning" in cleaned
    
    def test_removes_gutenberg_footer(self):
        """Test removal of Gutenberg footer."""
        text = """
        The end of the story.
        
        *** END OF THE PROJECT GUTENBERG EBOOK ***
        
        Project Gutenberg's license information...
        """
        
        cleaner = TextCleaner()
        cleaned = cleaner.clean(text)
        
        assert "end of the story" in cleaned
        assert "END OF THE PROJECT GUTENBERG" not in cleaned
        assert "license information" not in cleaned


class TestChapterSplitter:
    """Test chapter splitting logic."""
    
    def test_detects_chapter_patterns(self):
        """Test chapter boundary detection."""
        text = """
        CHAPTER I
        The Beginning
        
        This is the first chapter content.
        
        CHAPTER II
        The Middle
        
        This is the second chapter content.
        """
        
        splitter = ChapterSplitter("intermediate")
        chapters = splitter.split(text)
        
        assert len(chapters) >= 2
        assert any("Beginning" in c['title'] or "I" in c['title'] for c in chapters)
    
    def test_splits_long_chapters(self):
        """Test splitting of overly long chapters."""
        # Create a long chapter (3000 words)
        long_para = " ".join(["word"] * 500)
        text = f"CHAPTER I\n\n" + "\n\n".join([long_para] * 6)
        
        splitter = ChapterSplitter("beginner")  # Max 800 words
        chapters = splitter.split(text)
        
        # Should be split into multiple parts
        assert len(chapters) > 1
        
        # No chapter should exceed max significantly
        for chapter in chapters:
            assert chapter['word_count'] <= splitter.max_words + 200  # Some tolerance


class TestQuestionGenerator:
    """Test question generation."""
    
    @pytest.mark.skipif(
        not Path.home().joinpath('.ollama').exists(),
        reason="Ollama not installed"
    )
    def test_generates_questions(self):
        """Test question generation with Ollama."""
        generator = QuestionGenerator()
        
        chapter_text = """
        Alice was beginning to get very tired of sitting by her sister on the
        bank, and of having nothing to do. She was considering whether the
        pleasure of making a daisy-chain would be worth the trouble of getting
        up and picking the daisies, when suddenly a White Rabbit with pink eyes
        ran close by her.
        """
        
        questions = generator.generate_questions(
            title="Alice's Adventures in Wonderland",
            author="Lewis Carroll",
            chapter_number=1,
            chapter_title="Down the Rabbit-Hole",
            chapter_text=chapter_text,
            reading_level="intermediate",
            age_range="8-12",
            num_questions=2
        )
        
        assert len(questions) >= 1
        assert all('text' in q for q in questions)
        assert all('keywords' in q for q in questions)
    
    def test_fallback_questions(self):
        """Test fallback question generation."""
        generator = QuestionGenerator()
        
        questions = generator._generate_fallback_questions("Chapter 1", 3)
        
        assert len(questions) == 3
        assert all('text' in q for q in questions)
        assert all('keywords' in q for q in questions)


class TestDatabaseManager:
    """Test database operations."""
    
    def test_connection(self):
        """Test database connection."""
        db = DatabaseManager()
        assert db.test_connection() == True
    
    def test_check_duplicate(self):
        """Test duplicate book detection."""
        db = DatabaseManager()
        
        # This book shouldn't exist (random title)
        result = db.check_duplicate(
            "Test Book XYZ123",
            "Test Author XYZ123"
        )
        assert result is None