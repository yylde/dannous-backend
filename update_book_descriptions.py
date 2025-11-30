#!/usr/bin/env python3
"""
One-time script to regenerate descriptions for all published books using Gemini 2.0 Flash.
This script reads the full book text and generates new, sophisticated descriptions.
"""

import logging
import sys
from pathlib import Path
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import DatabaseManager
from src.question_generator import QuestionGenerator
from src.text_cleaner import TextCleaner
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def clean_book_text(html_text: str) -> str:
    """Clean HTML and Gutenberg headers from book text."""
    # Strip HTML tags
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    
    # Strip Gutenberg headers/footers
    cleaner = TextCleaner()
    clean_text = cleaner.clean(clean_text)
    
    # Normalize whitespace
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    return clean_text


def update_all_book_descriptions():
    """Update descriptions for all published books."""
    db = DatabaseManager()
    generator = QuestionGenerator()
    
    # Get all published books (not drafts) with their full text
    logger.info("Fetching all published books from database...")
    books = db.get_all_books_with_text()
    
    if not books:
        logger.warning("No books found in database")
        return
    
    logger.info(f"Found {len(books)} published books")
    
    success_count = 0
    error_count = 0
    
    for i, book in enumerate(books, 1):
        book_id = book.get('id')
        title = book.get('title', 'Unknown')
        author = book.get('author', 'Unknown')
        full_text = book.get('full_text', '')
        current_description = book.get('description', '')
        
        logger.info(f"\n[{i}/{len(books)}] Processing: {title} by {author}")
        logger.info(f"  Current description: {current_description[:100] if current_description else 'None'}...")
        
        if not full_text:
            logger.warning(f"  ⚠️  No full_text found for book {book_id}, skipping...")
            error_count += 1
            continue
        
        try:
            # Clean the book text (remove HTML, Gutenberg headers)
            logger.info(f"  Cleaning book text ({len(full_text)} chars)...")
            clean_text = clean_book_text(full_text)
            logger.info(f"  Cleaned text: {len(clean_text)} chars")
            
            # Generate new description using Gemini 2.0 Flash
            logger.info(f"  Generating description with Gemini 2.0 Flash...")
            description = generator.generate_description(
                title=title,
                author=author,
                book_text=clean_text,
                book_id=book_id,
                use_queue=False  # Direct call, no queue
            )
            
            # Update the book in database
            logger.info(f"  Updating database...")
            db.update_book(book_id, description=description)
            
            logger.info(f"  ✓ Success! New description: {description[:150]}...")
            success_count += 1
            
            # Wait 10 seconds between API calls to avoid rate limiting
            if i < len(books):  # Don't wait after the last book
                logger.info(f"  Waiting 10 seconds before next book to avoid rate limiting...")
                time.sleep(2)
            
        except Exception as e:
            logger.error(f"  ✗ Error processing book {book_id}: {e}")
            error_count += 1
            # Still wait on error to avoid hammering the API
            if i < len(books):
                logger.info(f"  Waiting 10 seconds before next book...")
                time.sleep(2)
            continue
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY:")
    logger.info(f"  Total books: {len(books)}")
    logger.info(f"  ✓ Successfully updated: {success_count}")
    logger.info(f"  ✗ Errors: {error_count}")
    logger.info(f"{'='*60}")



if __name__ == "__main__":
    logger.info("Starting book description update script...")
    logger.info("This will regenerate descriptions for ALL published books using Gemini 2.0 Flash")
    
    try:
        update_all_book_descriptions()
        logger.info("\n✓ Script completed successfully!")
    except Exception as e:
        logger.error(f"\n✗ Script failed: {e}")
        sys.exit(1)
