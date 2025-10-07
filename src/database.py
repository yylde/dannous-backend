"""Database operations for inserting processed books."""

import psycopg2
import json
from typing import Optional, List, Tuple
import logging
from contextmanager import contextmanager

from .config import settings
from .models import ProcessedBook, Book, Chapter, Question

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and operations."""
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize database manager."""
        self.database_url = database_url or settings.database_url
    
    @contextmanager
    def get_connection(self):
        """Get database connection context manager."""
        conn = None
        try:
            conn = psycopg2.connect(self.database_url)
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()
    
    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    version = cur.fetchone()[0]
                    logger.info(f"Connected to PostgreSQL: {version}")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False
    
    def check_duplicate(self, title: str, author: str) -> Optional[str]:
        """Check if book already exists. Returns book_id if found."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM books WHERE title = %s AND author = %s",
                        (title, author)
                    )
                    result = cur.fetchone()
                    if result:
                        return str(result[0])
            return None
        except Exception as e:
            logger.error(f"Error checking duplicate: {e}")
            return None
    
    def insert_book(self, book: Book) -> str:
        """Insert book record. Returns book_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO books (
                        id, title, author, description, age_range, reading_level,
                        genre, total_chapters, estimated_reading_time_minutes,
                        cover_image_url, isbn, publication_year,
                        is_active, content_rating, tags
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                """, (
                    book.id,
                    book.title,
                    book.author,
                    book.description,
                    book.age_range,
                    book.reading_level,
                    book.genre,
                    book.total_chapters,
                    book.estimated_reading_time_minutes,
                    book.cover_image_url,
                    book.isbn,
                    book.publication_year,
                    book.is_active,
                    book.content_rating,
                    Json(book.tags)
                ))
                book_id = cur.fetchone()[0]
                logger.info(f"Inserted book: {book.title} (ID: {book_id})")
                return str(book_id)
    
    def insert_chapter(self, chapter: Chapter) -> str:
        """Insert chapter record. Returns chapter_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chapters (
                        id, book_id, chapter_number, title, content,
                        word_count, estimated_reading_time_minutes,
                        vocabulary_words
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                """, (
                    chapter.id,
                    chapter.book_id,
                    chapter.chapter_number,
                    chapter.title,
                    chapter.content,
                    chapter.word_count,
                    chapter.estimated_reading_time_minutes,
                    Json(chapter.vocabulary_words)
                ))
                chapter_id = cur.fetchone()[0]
                return str(chapter_id)
    
    def insert_question(self, question: Question) -> str:
        """Insert question record. Returns question_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO questions (
                        id, book_id, chapter_id, question_text, question_type,
                        difficulty_level, expected_keywords, min_word_count,
                        max_word_count, order_index, is_active
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                """, (
                    question.id,
                    question.book_id,
                    question.chapter_id,
                    question.question_text,
                    question.question_type,
                    question.difficulty_level,
                    Json(question.expected_keywords),
                    question.min_word_count,
                    question.max_word_count,
                    question.order_index,
                    question.is_active
                ))
                question_id = cur.fetchone()[0]
                return str(question_id)
    
    def insert_processed_book(self, processed_book: ProcessedBook) -> Tuple[str, int, int]:
        """
        Insert complete processed book with all chapters and questions.
        Returns (book_id, num_chapters, num_questions).
        """
        # Check for duplicate
        existing_id = self.check_duplicate(
            processed_book.book.title,
            processed_book.book.author
        )
        if existing_id:
            raise ValueError(
                f"Book '{processed_book.book.title}' by {processed_book.book.author} "
                f"already exists (ID: {existing_id})"
            )
        
        try:
            # Insert book
            book_id = self.insert_book(processed_book.book)
            
            # Insert chapters
            chapter_count = 0
            for chapter in processed_book.chapters:
                self.insert_chapter(chapter)
                chapter_count += 1
            
            # Insert questions
            question_count = 0
            for question in processed_book.questions:
                self.insert_question(question)
                question_count += 1
            
            logger.info(
                f"Successfully inserted book '{processed_book.book.title}': "
                f"{chapter_count} chapters, {question_count} questions"
            )
            
            return book_id, chapter_count, question_count
            
        except Exception as e:
            logger.error(f"Failed to insert book: {e}")
            raise
    
    def list_books(self, limit: int = 50) -> List[dict]:
        """List books in database."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, title, author, total_chapters, age_range, 
                           reading_level, created_at
                    FROM books
                    WHERE is_active = true
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))
                
                columns = [desc[0] for desc in cur.description]
                results = []
                for row in cur.fetchall():
                    results.append(dict(zip(columns, row)))
                return results
    
    def get_book_stats(self, book_id: str) -> Optional[dict]:
        """Get statistics for a book."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        b.title,
                        b.author,
                        b.total_chapters,
                        COUNT(DISTINCT c.id) as actual_chapters,
                        COUNT(q.id) as total_questions
                    FROM books b
                    LEFT JOIN chapters c ON b.id = c.book_id
                    LEFT JOIN questions q ON b.id = q.book_id
                    WHERE b.id = %s
                    GROUP BY b.id, b.title, b.author, b.total_chapters
                """, (book_id,))
                
                result = cur.fetchone()
                if result:
                    return {
                        "title": result[0],
                        "author": result[1],
                        "total_chapters": result[2],
                        "actual_chapters": result[3],
                        "total_questions": result[4]
                    }
                return None