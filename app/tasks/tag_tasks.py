"""Background tasks for tag generation."""

import logging
from src.question_generator import QuestionGenerator
from src.database import DatabaseManager
from src.config import settings

logger = logging.getLogger(__name__)


def generate_tags_async(draft_id, title, author, age_range, reading_level):
    """Generate tags asynchronously in background for a book."""
    db = None
    try:
        db = DatabaseManager()
        
        generator = QuestionGenerator()
        tags_data = generator.generate_tags(
            title=title,
            author=author,
            reading_level=reading_level or settings.default_reading_level,
            age_range=age_range or settings.default_age_range,
            book_id=str(draft_id)
        )
        
        # Save tags to the draft (even if using fallback)
        if tags_data and len(tags_data) > 0:
            db.update_draft(draft_id, tags=tags_data)
            logger.info(f"✓ Generated {len(tags_data)} tags for draft {draft_id}: {tags_data}")
        else:
            logger.error(f"✗ No tags generated for draft {draft_id}")
        
    except Exception as e:
        logger.exception(f"✗ Failed to generate tags for draft {draft_id}: {e}")
        # Ensure tags are ALWAYS saved even on critical failure
        try:
            if db is None:
                db = DatabaseManager()
            
            # Try to save fallback tags
            generator = QuestionGenerator()
            fallback_tags = generator._generate_fallback_tags(reading_level or settings.default_reading_level)
            if fallback_tags:
                db.update_draft(draft_id, tags=fallback_tags)
                logger.warning(f"⚠ Used fallback tags for draft {draft_id}: {fallback_tags}")
        except Exception as fallback_error:
            logger.exception(f"✗ Failed to save fallback tags: {fallback_error}")
