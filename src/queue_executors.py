"""Direct execution functions for queue tasks.

CRITICAL: These functions call Ollama DIRECTLY without queueing.
They are meant to be called BY the queue worker, not to enqueue tasks.
"""

import logging
from typing import Dict, List, Any
import json

logger = logging.getLogger(__name__)


def execute_tag_generation(book_id: str, title: str, author: str, age_range: str, reading_level: str) -> List[str]:
    """
    Direct Ollama execution for tag generation - NO QUEUEING.
    
    Args:
        book_id: Draft book ID
        title: Book title
        author: Book author
        age_range: Target age range
        reading_level: Reading level
    
    Returns:
        List of generated tags
    """
    from src.question_generator import QuestionGenerator
    from src.database import DatabaseManager
    
    logger.info(f"[EXECUTOR] Generating tags for book: {title}")
    
    db = DatabaseManager()
    generator = QuestionGenerator()
    
    tags = generator.generate_tags(
        title=title,
        author=author,
        reading_level=reading_level,
        age_range=age_range,
        book_id=book_id,
        use_queue=False
    )
    
    db.update_draft(book_id, tags=tags, tag_status='ready')
    
    logger.info(f"[EXECUTOR] ✓ Tags generated and saved: {tags}")
    return tags


def execute_description_generation(book_id: str, title: str, author: str, text_sample: str = None) -> str:
    """
    Direct Ollama execution for description generation - NO QUEUEING.
    
    Args:
        book_id: Draft book ID
        title: Book title
        author: Book author
        text_sample: Optional book text sample for synopsis generation
    
    Returns:
        Generated description string
    """
    from src.question_generator import QuestionGenerator
    from src.database import DatabaseManager
    
    logger.info(f"[EXECUTOR] Generating description for book: {title}")
    
    db = DatabaseManager()
    generator = QuestionGenerator()
    
    description = generator.generate_description(
        title=title,
        author=author,
        book_text_sample=text_sample,
        book_id=book_id,
        use_queue=False
    )
    
    db.update_draft(book_id, description=description, description_status='ready')
    
    logger.info(f"[EXECUTOR] ✓ Description generated and saved: {description[:100]}...")
    return description


def execute_question_generation(
    book_id: str,
    chapter_id: str,
    title: str,
    author: str,
    chapter_number: int,
    chapter_title: str,
    chapter_text: str,
    reading_level: str,
    age_range: str,
    grade_level: str,
    num_questions: int = 3,
    vocab_count: int = 8
) -> Dict[str, Any]:
    """
    Direct Ollama execution for question generation - NO QUEUEING.
    
    Args:
        book_id: Draft book ID
        chapter_id: Chapter ID
        title: Book title
        author: Book author
        chapter_number: Chapter number
        chapter_title: Chapter title
        chapter_text: Chapter content
        reading_level: Reading level
        age_range: Age range
        grade_level: Specific grade level
        num_questions: Number of questions to generate (default: 3)
        vocab_count: Number of vocabulary words (default: 8)
    
    Returns:
        Dictionary with questions and vocabulary
    """
    from src.question_generator import QuestionGenerator
    from src.database import DatabaseManager
    
    logger.info(f"[EXECUTOR] Generating questions for chapter {chapter_number}: {chapter_title}")
    
    db = DatabaseManager()
    generator = QuestionGenerator()
    
    questions, vocabulary = generator.generate_questions(
        title=title,
        author=author,
        chapter_number=chapter_number,
        chapter_title=chapter_title,
        chapter_text=chapter_text,
        reading_level=reading_level,
        age_range=age_range,
        grade_level=grade_level,
        num_questions=num_questions,
        vocab_count=vocab_count,
        book_id=book_id,
        chapter_id=chapter_id,
        use_queue=False
    )
    
    db.save_draft_questions(
        chapter_id=chapter_id,
        draft_id=book_id,
        questions=questions,
        vocabulary=vocabulary,
        grade_level=grade_level
    )
    
    logger.info(f"[EXECUTOR] ✓ Generated {len(questions)} questions and {len(vocabulary)} vocab words")
    
    return {
        'questions': questions,
        'vocabulary': vocabulary
    }
