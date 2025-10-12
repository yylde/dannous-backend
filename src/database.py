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
                     genre: str, metadata: dict, full_html: str = None) -> str:
        """Create a new book draft. Returns draft_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO book_drafts (
                        gutenberg_id, title, author, full_text, full_html, age_range, 
                        reading_level, genre, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (gutenberg_id, title, author, full_text, full_html, age_range, 
                      reading_level, genre, json.dumps(metadata)))
                draft_id = cur.fetchone()[0]
                logger.info(f"Created draft: {title} (ID: {draft_id})")
                return str(draft_id)
    
    def update_draft(self, draft_id: str, **kwargs) -> None:
        """Update draft metadata."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Build dynamic update query
                set_clauses = []
                values = []
                for key, value in kwargs.items():
                    if key == 'metadata':
                        set_clauses.append(f"{key} = %s")
                        values.append(json.dumps(value))
                    else:
                        set_clauses.append(f"{key} = %s")
                        values.append(value)
                
                if set_clauses:
                    set_clauses.append("updated_at = NOW()")
                    values.append(draft_id)
                    query = f"UPDATE book_drafts SET {', '.join(set_clauses)} WHERE id = %s"
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
                    FROM book_drafts bd
                    LEFT JOIN draft_chapters dc ON bd.id = dc.draft_id
                    WHERE bd.is_completed = false
                    GROUP BY bd.id
                    ORDER BY bd.updated_at DESC
                """)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
    
    def get_draft(self, draft_id: str) -> Optional[dict]:
        """Get a specific draft with all its data."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, gutenberg_id, title, author, full_text, full_html,
                           age_range, reading_level, genre, metadata, 
                           created_at, updated_at
                    FROM book_drafts
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
                
                return draft
    
    def save_draft_chapter(self, draft_id: str, chapter_number: int, title: str, 
                          content: str, word_count: int, html_formatting: str = None) -> str:
        """Save a chapter to a draft. Returns chapter_id."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO draft_chapters (
                        draft_id, chapter_number, title, content, 
                        word_count, html_formatting, question_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'pending')
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
                cur.execute("UPDATE book_drafts SET updated_at = NOW() WHERE id = %s", (draft_id,))
                return str(chapter_id)
    
    def get_draft_chapters(self, draft_id: str) -> List[dict]:
        """Get all chapters for a draft."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, chapter_number, title, content, word_count, 
                           html_formatting, has_questions, question_status, created_at
                    FROM draft_chapters
                    WHERE draft_id = %s
                    ORDER BY chapter_number
                """, (draft_id,))
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
    
    def get_draft_chapter(self, chapter_id: str) -> Optional[dict]:
        """Get a specific draft chapter with questions and vocabulary."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get chapter
                cur.execute("""
                    SELECT id, draft_id, chapter_number, title, content, 
                           word_count, html_formatting, has_questions, question_status
                    FROM draft_chapters
                    WHERE id = %s
                """, (chapter_id,))
                result = cur.fetchone()
                if not result:
                    return None
                
                columns = [desc[0] for desc in cur.description]
                chapter = dict(zip(columns, result))
                
                # Get questions
                cur.execute("""
                    SELECT id, question_text, question_type, difficulty_level, 
                           expected_keywords, min_word_count, max_word_count, order_index
                    FROM draft_questions
                    WHERE chapter_id = %s
                    ORDER BY order_index
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
                
                # Get vocabulary
                cur.execute("""
                    SELECT id, word, definition, example
                    FROM draft_vocabulary
                    WHERE chapter_id = %s
                """, (chapter_id,))
                columns = [desc[0] for desc in cur.description]
                chapter['vocabulary'] = [dict(zip(columns, row)) for row in cur.fetchall()]
                
                return chapter
    
    def update_chapter_question_status(self, chapter_id: str, status: str) -> None:
        """Update question generation status for a chapter."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_chapters 
                    SET question_status = %s,
                        has_questions = CASE WHEN %s = 'ready' THEN true ELSE has_questions END
                    WHERE id = %s
                """, (status, status, chapter_id))
    
    def save_draft_questions(self, chapter_id: str, draft_id: str, 
                            questions: List[dict], vocabulary: List[dict]) -> None:
        """Save generated questions and vocabulary for a draft chapter."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Delete existing questions and vocabulary
                cur.execute("DELETE FROM draft_questions WHERE chapter_id = %s", (chapter_id,))
                cur.execute("DELETE FROM draft_vocabulary WHERE chapter_id = %s", (chapter_id,))
                
                # Insert questions
                for i, q in enumerate(questions, 1):
                    cur.execute("""
                        INSERT INTO draft_questions (
                            draft_id, chapter_id, question_text, question_type,
                            difficulty_level, expected_keywords, min_word_count,
                            max_word_count, order_index
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        draft_id, chapter_id, q['text'], q.get('type', 'comprehension'),
                        q.get('difficulty', 'medium'), json.dumps(q.get('keywords', [])),
                        q.get('min_words', 20), q.get('max_words', 200), i
                    ))
                
                # Insert vocabulary
                for v in vocabulary:
                    cur.execute("""
                        INSERT INTO draft_vocabulary (chapter_id, word, definition, example)
                        VALUES (%s, %s, %s, %s)
                    """, (chapter_id, v['word'], v['definition'], v.get('example', '')))
                
                # Update chapter status
                cur.execute("""
                    UPDATE draft_chapters 
                    SET has_questions = true, question_status = 'ready'
                    WHERE id = %s
                """, (chapter_id,))
    
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
                
                # Delete chapter (cascade will delete questions/vocab)
                cur.execute("DELETE FROM draft_chapters WHERE id = %s", (chapter_id,))
                
                # Update draft timestamp
                cur.execute("UPDATE book_drafts SET updated_at = NOW() WHERE id = %s", (draft_id,))
                
                return {'content': content, 'chapter_number': chapter_number}
    
    def finalize_draft(self, draft_id: str) -> Tuple[str, int, int]:
        """Move draft to main books table. Returns (book_id, chapters, questions)."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get draft data
                cur.execute("""
                    SELECT title, author, age_range, reading_level, genre, metadata
                    FROM book_drafts WHERE id = %s
                """, (draft_id,))
                draft = cur.fetchone()
                if not draft:
                    raise ValueError(f"Draft {draft_id} not found")
                
                title, author, age_range, reading_level, genre, metadata = draft
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
                
                cur.execute("""
                    INSERT INTO books (
                        id, title, author, age_range, reading_level, genre,
                        total_chapters, isbn, publication_year
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (book_id, title, author, age_range, reading_level, genre,
                      total_chapters, metadata.get('isbn'), metadata.get('publication_year')))
                
                # Copy chapters
                chapter_id_map = {}
                for dc in draft_chapters:
                    old_id, num, ch_title, content, word_count, html = dc
                    new_id = str(uuid4())
                    chapter_id_map[str(old_id)] = new_id
                    
                    # Get vocabulary for this chapter
                    cur.execute("""
                        SELECT word, definition, example
                        FROM draft_vocabulary WHERE chapter_id = %s
                    """, (str(old_id),))
                    vocab = [{'word': r[0], 'definition': r[1], 'example': r[2]} 
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
                    UPDATE book_drafts SET is_completed = true, updated_at = NOW()
                    WHERE id = %s
                """, (draft_id,))
                
                logger.info(f"Finalized draft {draft_id} to book {book_id}: "
                           f"{total_chapters} chapters, {question_count} questions")
                
                return book_id, total_chapters, question_count


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