"""Data models matching the database schema."""

from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field


class Book(BaseModel):
    """Book model matching database schema."""
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(..., max_length=500)
    author: str = Field(..., max_length=300)
    description: Optional[str] = None
    age_range: str = Field(..., max_length=20)
    reading_level: str = Field(..., max_length=20)
    genre: Optional[str] = Field(None, max_length=100)
    total_chapters: int
    estimated_reading_time_minutes: Optional[int] = None
    cover_image_url: Optional[str] = Field(None, max_length=500)
    isbn: Optional[str] = Field(None, max_length=20)
    publication_year: Optional[int] = None
    content_rating: Optional[str] = Field(None, max_length=20)
    tags: List[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class Chapter(BaseModel):
    """Chapter model matching database schema."""
    id: UUID = Field(default_factory=uuid4)
    book_id: UUID
    chapter_number: int
    title: str = Field(..., max_length=300)
    content: str
    word_count: int
    estimated_reading_time_minutes: int
    vocabulary_words: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class Question(BaseModel):
    """Question model matching database schema."""
    id: UUID = Field(default_factory=uuid4)
    book_id: UUID
    chapter_id: UUID
    question_text: str
    question_type: str = "comprehension"
    difficulty_level: str = "medium"
    expected_keywords: List[str] = Field(default_factory=list)
    min_word_count: int = 20
    max_word_count: int = 200
    order_index: int
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class ProcessedBook(BaseModel):
    """Complete processed book with chapters and questions."""
    book: Book
    chapters: List[Chapter]
    questions: List[Question]
    
    def get_statistics(self) -> dict:
        """Get processing statistics."""
        total_words = sum(c.word_count for c in self.chapters)
        total_questions = len(self.questions)
        
        return {
            "title": self.book.title,
            "author": self.book.author,
            "total_chapters": len(self.chapters),
            "total_questions": total_questions,
            "total_words": total_words,
            "estimated_reading_time_minutes": self.book.estimated_reading_time_minutes,
            "book_id": str(self.book.id)
        }