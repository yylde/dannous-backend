"""Database operations for inserting processed books."""

import psycopg2
import json
from typing import Optional, List, Tuple
import logging
from contextlib import contextmanager

from .config import settings
from .models import ProcessedBook, Book, Chapter, Question
import re
import html

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
                    str(book.id),
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
                    json.dumps(book.tags)
                ))
                book_id = cur.fetchone()[0]
                logger.info(f"Inserted book: {book.title} (ID: {book_id})")
                return str(book_id)
    
    def insert_chapter(self, chapter: Chapter) -> str:
        """Insert a chapter. Returns chapter_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chapters (
                        id, book_id, chapter_number, title, content,
                        word_count, estimated_reading_time_minutes,
                        vocabulary_words, html_formatting, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    str(chapter.id),
                    str(chapter.book_id),
                    chapter.chapter_number,
                    chapter.title,
                    chapter.content,
                    chapter.word_count,
                    chapter.estimated_reading_time_minutes,
                    json.dumps(chapter.vocabulary_words),
                    chapter.html_formatting,
                    chapter.created_at
                ))
                # Don't fetch, just return the ID we already have
                return str(chapter.id)
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
                    str(question.id),
                    str(question.book_id),
                    str(question.chapter_id),
                    question.question_text,
                    question.question_type,
                    question.difficulty_level,
                    json.dumps(question.expected_keywords),
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
    
    # ==================== DRAFT METHODS ====================
    
    def create_draft(self, gutenberg_id: Optional[int], title: str, author: str, 
                     full_text: str, age_range: str, reading_level: str, 
                     genre: str, metadata: dict, full_html: str = None, 
                     cover_image_url: str = None, word_count: int = None,
                     html_sections: list = None, text_sections: list = None) -> str:
        """Create a new book draft. Returns draft_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO draft_books (
                        gutenberg_id, title, author, full_text, full_html, age_range, 
                        reading_level, genre, cover_image_url, metadata, word_count,
                        html_sections, text_sections
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (gutenberg_id, title, author, full_text, full_html, age_range, 
                      reading_level, genre, cover_image_url, json.dumps(metadata), word_count,
                      json.dumps(html_sections or []), json.dumps(text_sections or [])))
                draft_id = cur.fetchone()[0]
                logger.info(f"Created draft: {title} (ID: {draft_id}, {word_count or 'unknown'} words)")
                return str(draft_id)
    
    def update_draft(self, draft_id: str, **kwargs) -> None:
        """Update draft metadata."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Build dynamic update query
                set_clauses = []
                values = []
                for key, value in kwargs.items():
                    if key == 'cover_image_url' and (value is None or value == ''):
                        continue
                    if key in ('tag_status', 'description_status'):
                        logger.debug(f"Skipping dropped column {key} in update_draft")
                        continue
                    if key in ('metadata', 'tags', 'last_marker_position'):
                        set_clauses.append(f"{key} = %s")
                        values.append(json.dumps(value))
                    else:
                        set_clauses.append(f"{key} = %s")
                        values.append(value)
                
                if set_clauses:
                    set_clauses.append("updated_at = NOW()")
                    values.append(draft_id)
                    query = f"UPDATE draft_books SET {', '.join(set_clauses)} WHERE id = %s"
                    cur.execute(query, values)
    
    def get_all_drafts(self) -> List[dict]:
        """Get all incomplete drafts."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        bd.id,
                        bd.title,
                        bd.author,
                        bd.gutenberg_id,
                        bd.age_range,
                        bd.reading_level,
                        bd.created_at,
                        bd.updated_at,
                        COUNT(dc.id) as chapter_count
                    FROM draft_books bd
                    LEFT JOIN draft_chapters dc ON bd.id = dc.draft_id
                    WHERE bd.is_completed = false
                    GROUP BY bd.id
                    ORDER BY bd.updated_at DESC
                """)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
    
    def get_draft_by_gutenberg_id(self, gutenberg_id: int) -> Optional[dict]:
        """Check if a draft with this Gutenberg ID already exists."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, title, author, created_at
                    FROM draft_books
                    WHERE gutenberg_id = %s AND is_completed = false
                    LIMIT 1
                """, (gutenberg_id,))
                row = cur.fetchone()
                if row:
                    return {
                        'id': str(row[0]),
                        'title': row[1],
                        'author': row[2],
                        'created_at': row[3].isoformat() if row[3] else None
                    }
                return None
    
    def get_draft(self, draft_id: str) -> Optional[dict]:
        """Get a specific draft with all its data."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, gutenberg_id, title, author, full_text, full_html,
                           age_range, reading_level, genre, cover_image_url, metadata, 
                           tags, description, created_at, updated_at,
                           html_sections, text_sections
                    FROM draft_books
                    WHERE id = %s
                """, (draft_id,))
                result = cur.fetchone()
                if not result:
                    return None
                
                columns = [desc[0] for desc in cur.description]
                draft = dict(zip(columns, result))
                
                # metadata is JSONB - already parsed by psycopg2
                if isinstance(draft['metadata'], str):
                    draft['metadata'] = json.loads(draft['metadata'])
                elif draft['metadata'] is None:
                    draft['metadata'] = {}
                
                # tags is also JSONB - parse it
                if isinstance(draft.get('tags'), str):
                    draft['tags'] = json.loads(draft['tags'])
                elif draft.get('tags') is None:
                    draft['tags'] = []
                
                # html_sections and text_sections are JSONB arrays
                if isinstance(draft.get('html_sections'), str):
                    draft['html_sections'] = json.loads(draft['html_sections'])
                elif draft.get('html_sections') is None:
                    draft['html_sections'] = []
                    
                if isinstance(draft.get('text_sections'), str):
                    draft['text_sections'] = json.loads(draft['text_sections'])
                elif draft.get('text_sections') is None:
                    draft['text_sections'] = []
                
                return draft
    
    def save_draft_chapter(self, draft_id: str, chapter_number: int, title: str, 
                          content: str, word_count: int, html_formatting: str = None) -> str:
        """Save a chapter to a draft. Returns chapter_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO draft_chapters (
                        draft_id, chapter_number, title, content, 
                        word_count, html_formatting
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (draft_id, chapter_number) 
                    DO UPDATE SET 
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        word_count = EXCLUDED.word_count,
                        html_formatting = EXCLUDED.html_formatting
                    RETURNING id
                """, (draft_id, chapter_number, title, content, word_count, html_formatting))
                chapter_id = cur.fetchone()[0]
                
                # Update draft timestamp
                cur.execute("UPDATE draft_books SET updated_at = NOW() WHERE id = %s", (draft_id,))
                return str(chapter_id)
    
    def get_draft_chapters(self, draft_id: str) -> List[dict]:
        """Get all chapters for a draft."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, chapter_number, title, content, word_count, 
                           html_formatting, created_at
                    FROM draft_chapters
                    WHERE draft_id = %s
                    ORDER BY chapter_number
                """, (draft_id,))
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
    
    def update_draft_chapter(self, chapter_id: str, title: str = None, 
                            content: str = None, html_formatting: str = None) -> bool:
        """Update a draft chapter's content and/or HTML by ID. Returns True if successful."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Build dynamic update query based on provided parameters
                update_fields = []
                params = []
                
                if title is not None:
                    update_fields.append("title = %s")
                    params.append(title)
                
                if content is not None:
                    update_fields.append("content = %s")
                    params.append(content)
                    # Update word count if content is provided
                    word_count = len(content.split()) if content else 0
                    update_fields.append("word_count = %s")
                    params.append(word_count)
                
                if html_formatting is not None:
                    update_fields.append("html_formatting = %s")
                    params.append(html_formatting)
                
                if not update_fields:
                    return False
                
                params.append(chapter_id)
                query = f"UPDATE draft_chapters SET {', '.join(update_fields)} WHERE id = %s"
                cur.execute(query, params)
                
                # Update draft timestamp
                cur.execute("""
                    UPDATE draft_books SET updated_at = NOW() 
                    WHERE id = (SELECT draft_id FROM draft_chapters WHERE id = %s)
                """, (chapter_id,))
                
                return cur.rowcount > 0
    
    def get_draft_chapter(self, chapter_id: str) -> Optional[dict]:
        """Get a specific draft chapter with questions and vocabulary."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get chapter
                cur.execute("""
                    SELECT id, draft_id, chapter_number, title, content, 
                           word_count, html_formatting
                    FROM draft_chapters
                    WHERE id = %s
                """, (chapter_id,))
                result = cur.fetchone()
                if not result:
                    return None
                
                columns = [desc[0] for desc in cur.description]
                chapter = dict(zip(columns, result))
                
                # Get questions with grade_level
                cur.execute("""
                    SELECT id, question_text, question_type, difficulty_level, 
                           expected_keywords, min_word_count, max_word_count, order_index, grade_level
                    FROM draft_questions
                    WHERE chapter_id = %s
                    ORDER BY grade_level, order_index
                """, (chapter_id,))
                columns = [desc[0] for desc in cur.description]
                questions = [dict(zip(columns, row)) for row in cur.fetchall()]
                for q in questions:
                    # JSONB fields are already parsed by psycopg2, no need to json.loads()
                    if isinstance(q['expected_keywords'], str):
                        q['expected_keywords'] = json.loads(q['expected_keywords'])
                    elif q['expected_keywords'] is None:
                        q['expected_keywords'] = []
                chapter['questions'] = questions
                
                # Get vocabulary with grade_level
                cur.execute("""
                    SELECT id, word, definition, example, grade_level
                    FROM draft_vocabulary
                    WHERE chapter_id = %s
                    ORDER BY grade_level, word
                """, (chapter_id,))
                columns = [desc[0] for desc in cur.description]
                chapter['vocabulary'] = [dict(zip(columns, row)) for row in cur.fetchall()]
                
                return chapter
    
    def update_question(self, question_id: str, question_text: str, question_type: str, 
                       difficulty_level: str, expected_keywords: List[str], 
                       min_word_count: int, max_word_count: int) -> None:
        """Update a draft question."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_questions 
                    SET question_text = %s,
                        question_type = %s,
                        difficulty_level = %s,
                        expected_keywords = %s,
                        min_word_count = %s,
                        max_word_count = %s
                    WHERE id = %s
                """, (question_text, question_type, difficulty_level, 
                      json.dumps(expected_keywords), min_word_count, max_word_count, question_id))
    
    def delete_question(self, question_id: str) -> None:
        """Delete a draft question."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM draft_questions WHERE id = %s", (question_id,))
    
    def update_vocabulary(self, vocab_id: str, word: str, definition: str, example: str) -> None:
        """Update a draft vocabulary item."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_vocabulary 
                    SET word = %s,
                        definition = %s,
                        example = %s
                    WHERE id = %s
                """, (word, definition, example, vocab_id))
    
    def delete_vocabulary(self, vocab_id: str) -> None:
        """Delete a draft vocabulary item."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM draft_vocabulary WHERE id = %s", (vocab_id,))
    
    def delete_questions_by_grade_level(self, draft_id: str, grade_levels: List[str]) -> None:
        """Delete all questions and vocabulary for specific grade levels in a draft."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for grade_level in grade_levels:
                    cur.execute("""
                        DELETE FROM draft_questions 
                        WHERE draft_id = %s AND grade_level = %s
                    """, (draft_id, grade_level))
                    cur.execute("""
                        DELETE FROM draft_vocabulary 
                        WHERE chapter_id IN (
                            SELECT id FROM draft_chapters WHERE draft_id = %s
                        ) AND grade_level = %s
                    """, (draft_id, grade_level))
    
    def get_existing_grade_levels_for_draft(self, draft_id: str) -> List[str]:
        """Get all unique grade levels that have questions in this draft."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT grade_level 
                    FROM draft_questions 
                    WHERE draft_id = %s AND grade_level IS NOT NULL
                    ORDER BY grade_level
                """, (draft_id,))
                return [row[0] for row in cur.fetchall()]
    
    
    def save_draft_questions(self, chapter_id: str, draft_id: str, 
                            questions: List[dict], vocabulary: List[dict], grade_level: str = None) -> None:
        """Save generated questions and vocabulary for a draft chapter."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Delete existing questions and vocabulary for this grade level only
                if grade_level:
                    cur.execute("DELETE FROM draft_questions WHERE chapter_id = %s AND grade_level = %s", (chapter_id, grade_level))
                    cur.execute("DELETE FROM draft_vocabulary WHERE chapter_id = %s AND grade_level = %s", (chapter_id, grade_level))
                
                # Insert questions with grade_level
                for i, q in enumerate(questions, 1):
                    cur.execute("""
                        INSERT INTO draft_questions (
                            draft_id, chapter_id, question_text, question_type,
                            difficulty_level, expected_keywords, min_word_count,
                            max_word_count, order_index, grade_level
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        draft_id, chapter_id, q['text'], q.get('type', 'comprehension'),
                        q.get('difficulty', 'medium'), json.dumps(q.get('keywords', [])),
                        q.get('min_words', 20), q.get('max_words', 200), i, grade_level
                    ))
                
                # Insert vocabulary with grade_level
                for v in vocabulary:
                    cur.execute("""
                        INSERT INTO draft_vocabulary (chapter_id, word, definition, example, grade_level)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (chapter_id, v['word'], v['definition'], v.get('example', ''), v.get('grade_level', grade_level)))
                
                # Note: Don't update status here - status is managed by generate_questions_async
                # which sets it to 'ready' only after ALL grade levels are processed
    
    def delete_draft_chapter(self, chapter_id: str) -> Optional[dict]:
        """Delete a draft chapter and return its content for restoration."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get chapter content before deletion
                cur.execute("""
                    SELECT content, chapter_number, draft_id
                    FROM draft_chapters
                    WHERE id = %s
                """, (chapter_id,))
                result = cur.fetchone()
                if not result:
                    return None
                
                content, chapter_number, draft_id = result
                
                # Delete pending queue tasks for this chapter using queue_manager_v2
                from .queue_manager_v2 import get_queue_manager_v2
                queue_manager_v2 = get_queue_manager_v2()
                with queue_manager_v2._get_connection() as qconn:
                    with qconn.cursor() as qcur:
                        qcur.execute("""
                            DELETE FROM queue_tasks
                            WHERE status = 'queued'
                              AND book_id = %s
                              AND chapter_id = %s
                        """, (draft_id, chapter_id))
                        qconn.commit()
                
                # Delete chapter (cascade will delete questions/vocab)
                cur.execute("DELETE FROM draft_chapters WHERE id = %s", (chapter_id,))
                
                # Update draft timestamp
                cur.execute("UPDATE draft_books SET updated_at = NOW() WHERE id = %s", (draft_id,))
                
                return {'content': content, 'chapter_number': chapter_number}
    
    def delete_draft(self, draft_id: str) -> bool:
        """Delete a draft and all its associated data (chapters, questions, vocabulary)."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM draft_books WHERE id = %s", (draft_id,))
                if not cur.fetchone():
                    return False
                
                cur.execute("DELETE FROM draft_books WHERE id = %s", (draft_id,))
                return True
    
    def finalize_draft(self, draft_id: str) -> Tuple[str, int, int]:
        """Move draft to main books table. Returns (book_id, chapters, questions)."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get draft data
                cur.execute("""
                    SELECT title, author, age_range, reading_level, genre, cover_image_url, metadata, tags, word_count, description
                    FROM draft_books WHERE id = %s
                """, (draft_id,))
                draft = cur.fetchone()
                if not draft:
                    raise ValueError(f"Draft {draft_id} not found")
                
                title, author, age_range, reading_level, genre, cover_image_url, metadata, tags, word_count, description = draft
                # JSONB fields are already parsed by psycopg2
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                elif metadata is None:
                    metadata = {}
                
                # Get chapters
                cur.execute("""
                    SELECT id, chapter_number, title, content, word_count, html_formatting
                    FROM draft_chapters WHERE draft_id = %s ORDER BY chapter_number
                """, (draft_id,))
                draft_chapters = cur.fetchall()
                
                # Create book
                from uuid import uuid4
                book_id = str(uuid4())
                total_chapters = len(draft_chapters)
                
                # Parse tags (JSONB is already parsed by psycopg2)
                if isinstance(tags, str):
                    tags = json.loads(tags)
                elif tags is None:
                    tags = []
                
                cur.execute("""
                    INSERT INTO books (
                        id, title, author, age_range, reading_level, genre,
                        total_chapters, cover_image_url, isbn, publication_year, tags, word_count, description
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (book_id, title, author, age_range, reading_level, genre,
                      total_chapters, cover_image_url, metadata.get('isbn'), metadata.get('publication_year'), json.dumps(tags), word_count, description))
                
                # Copy chapters
                chapter_id_map = {}
                for dc in draft_chapters:
                    old_id, num, ch_title, content, word_count, html = dc
                    new_id = str(uuid4())
                    chapter_id_map[str(old_id)] = new_id
                    
                    # Get vocabulary for this chapter
                    cur.execute("""
                        SELECT word, definition, example, grade_level
                        FROM draft_vocabulary WHERE chapter_id = %s
                    """, (str(old_id),))
                    vocab = [{'word': r[0], 'definition': r[1], 'example': r[2], 'grade_level': r[3]} 
                            for r in cur.fetchall()]
                    
                    cur.execute("""
                        INSERT INTO chapters (
                            id, book_id, chapter_number, title, content,
                            word_count, estimated_reading_time_minutes,
                            vocabulary_words, html_formatting
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (new_id, book_id, num, ch_title, content, word_count,
                          word_count // 200, json.dumps(vocab), html))
                
                # Copy questions
                question_count = 0
                for old_chapter_id, new_chapter_id in chapter_id_map.items():
                    cur.execute("""
                        SELECT question_text, question_type, difficulty_level,
                               expected_keywords, min_word_count, max_word_count, order_index
                        FROM draft_questions WHERE chapter_id = %s
                    """, (old_chapter_id,))
                    for q in cur.fetchall():
                        # expected_keywords is already parsed as a list by psycopg2
                        # Convert back to JSON for insertion
                        keywords = q[3] if isinstance(q[3], str) else json.dumps(q[3]) if q[3] else json.dumps([])
                        
                        cur.execute("""
                            INSERT INTO questions (
                                id, book_id, chapter_id, question_text, question_type,
                                difficulty_level, expected_keywords, min_word_count,
                                max_word_count, order_index
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                        """, (str(uuid4()), book_id, new_chapter_id, q[0], q[1], q[2],
                              keywords, q[4], q[5], q[6]))
                        question_count += 1
                
                # Mark draft as completed
                cur.execute("""
                    UPDATE draft_books SET is_completed = true, updated_at = NOW()
                    WHERE id = %s
                """, (draft_id,))
                
                logger.info(f"Finalized draft {draft_id} to book {book_id}: "
                           f"{total_chapters} chapters, {question_count} questions")
                
                return book_id, total_chapters, question_count
    
    def get_chapter_vocabulary(self, chapter_id: str) -> List[dict]:
        """Get all vocabulary for a chapter. Returns list of dicts with 'word', 'definition', 'grade_level' keys."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT word, definition, grade_level
                    FROM draft_vocabulary
                    WHERE chapter_id = %s
                    ORDER BY word
                """, (chapter_id,))
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]


def inject_vocabulary_abbr(html_content: str, vocabulary_list: List[dict]) -> str:
    """
    Inject vocabulary <abbr> tags into HTML content.
    
    Args:
        html_content: HTML string with paragraph and formatting tags
        vocabulary_list: List of dicts with 'word' and 'definition' keys
    
    Returns:
        HTML string with vocabulary words wrapped in <abbr> tags
    """
    if not vocabulary_list or not html_content:
        return html_content
    
    result = html_content
    
    # Process each vocabulary word
    for vocab in vocabulary_list:
        word = vocab.get('word', '').strip()
        definition = vocab.get('definition', '').strip()
        
        if not word or not definition:
            continue
        
        # Escape definition for HTML attribute
        escaped_definition = html.escape(definition, quote=True)
        
        # Create regex pattern for whole word matching (case-insensitive)
        # \b ensures word boundaries
        pattern = r'\b(' + re.escape(word) + r')\b'
        
        # Function to check if match is inside HTML tag
        def replace_if_not_in_tag(match):
            # Get the matched word
            matched_word = match.group(1)
            
            # Get context around match to check if it's inside a tag
            start_pos = match.start()
            
            # Check if we're inside an HTML tag by looking backwards
            before_match = result[:start_pos]
            last_open = before_match.rfind('<')
            last_close = before_match.rfind('>')
            
            # If last '<' is after last '>', we're inside a tag
            if last_open > last_close:
                return matched_word
            
            # Check if already wrapped in abbr
            if '<abbr' in before_match[-50:]:  # Check recent context
                return matched_word
            
            # Return abbr-wrapped version
            return f'<abbr title="{escaped_definition}">{matched_word}</abbr>'
        
        # Replace only the first occurrence
        result = re.sub(pattern, replace_if_not_in_tag, result, count=1, flags=re.IGNORECASE)
    
    return result