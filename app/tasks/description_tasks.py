"""Background tasks for description generation."""

import logging
from src.question_generator import QuestionGenerator
from src.database import DatabaseManager

logger = logging.getLogger(__name__)


def generate_description_async(draft_id, title, author, full_text, age_range, reading_level):
    """Generate description asynchronously in background for a book."""
    try:
        db = DatabaseManager()
        
        generator = QuestionGenerator()
        description = generator.generate_description(
            title=title,
            author=author,
            book_text_sample=full_text if full_text else None,
            book_id=str(draft_id)
        )
        
        # Save description to the draft
        if description:
            db.update_draft(draft_id, description=description)
            logger.info(f"✓ Generated description for draft {draft_id}: {description[:100]}...")
        else:
            logger.error(f"✗ No description generated for draft {draft_id}")
        
    except Exception as e:
        logger.exception(f"✗ Failed to generate description for draft {draft_id}: {e}")
