"""Routes for draft book management."""

import logging
import threading
from flask import Blueprint, request, jsonify
from uuid import uuid4

from src.database import DatabaseManager
from src.models import Book, Chapter, Question, ProcessedBook
from src.config import settings
from src.chapter_splitter import calculate_reading_time
from src.status_calculator import get_question_status

drafts_bp = Blueprint('drafts', __name__)
logger = logging.getLogger(__name__)


@drafts_bp.route('/drafts', methods=['GET'])
def get_drafts():
    """Get all incomplete drafts."""
    try:
        db = DatabaseManager()
        drafts = db.get_all_drafts()
        return jsonify({'success': True, 'drafts': drafts})
    except Exception as e:
        logger.exception("Failed to get drafts")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>', methods=['GET'])
def get_draft(draft_id):
    """Get a specific draft with chapters."""
    try:
        from src.status_calculator import get_tag_status, get_description_status, get_question_status
        
        db = DatabaseManager()
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Calculate dynamic status
        draft['tag_status'] = get_tag_status(draft_id)
        draft['description_status'] = get_description_status(draft_id)
        
        chapters = db.get_draft_chapters(draft_id)
        
        # Add question status to each chapter
        for chapter in chapters:
            chapter['question_status'] = get_question_status(chapter['id'])
        
        draft['chapters'] = chapters
        
        return jsonify({'success': True, 'draft': draft})
    except Exception as e:
        logger.exception("Failed to get draft")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft', methods=['POST'])
def create_or_update_draft():
    """Create or update a draft."""
    try:
        data = request.json
        draft_id = data.get('draft_id')
        
        db = DatabaseManager()
        
        if draft_id:
            # Update existing draft
            update_fields = {}
            for field in ['age_range', 'reading_level', 'genre', 'cover_image_url']:
                if field in data:
                    update_fields[field] = data[field]
            if update_fields:
                db.update_draft(draft_id, **update_fields)
            return jsonify({'success': True, 'draft_id': draft_id})
        else:
            # Check if a draft with this Gutenberg ID already exists
            # Normalize the input (strip whitespace, convert to int)
            gutenberg_id = data.get('gutenberg_id')
            if gutenberg_id:
                # Normalize to integer to avoid string formatting issues
                try:
                    gutenberg_id = int(str(gutenberg_id).strip())
                except (ValueError, TypeError):
                    pass
                existing_draft = db.get_draft_by_gutenberg_id(gutenberg_id)
                if existing_draft:
                    logger.info(f"Draft with Gutenberg ID {gutenberg_id} already exists: {existing_draft['id']}")
                    return jsonify({
                        'error': f"A draft for this book already exists: '{existing_draft['title']}' by {existing_draft['author']}",
                        'existing_draft_id': existing_draft['id']
                    }), 409
            
            # Calculate word count
            full_text = data.get('full_text', '')
            word_count = len(full_text.split()) if full_text else 0
            
            # Create new draft - database connection closes automatically at end of context
            draft_id = db.create_draft(
                gutenberg_id=data.get('gutenberg_id'),
                title=data.get('title'),
                author=data.get('author'),
                full_text=full_text,
                age_range=data.get('age_range', settings.default_age_range),
                reading_level=data.get('reading_level', settings.default_reading_level),
                genre=data.get('genre', settings.default_genre),
                cover_image_url=data.get('cover_image_url'),
                metadata=data.get('metadata', {}),
                full_html=data.get('full_html'),
                word_count=word_count
            )
            
            # Database connection is now closed and transaction committed
            logger.info(f"Created draft {draft_id}")
            
            return jsonify({'success': True, 'draft_id': draft_id})
    
    except Exception as e:
        logger.exception("Failed to save draft")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>', methods=['DELETE'])
def delete_draft(draft_id):
    """Delete a draft and all its associated data."""
    try:
        db = DatabaseManager()
        success = db.delete_draft(draft_id)
        if not success:
            return jsonify({'error': 'Draft not found'}), 404
        
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to delete draft")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft-tags-url/<draft_id>', methods=['PUT'])
def update_draft_tags_url(draft_id):
    """Update tags and cover URL for a draft."""
    try:
        data = request.json
        tags = data.get('tags', [])
        cover_image_url = data.get('cover_image_url', '')
        
        db = DatabaseManager()
        
        # Update draft with unpacked keyword arguments
        db.update_draft(draft_id, tags=tags, cover_image_url=cover_image_url)
        
        return jsonify({
            'success': True,
            'message': 'Tags and cover URL updated successfully'
        })
    except Exception as e:
        logger.exception("Failed to update tags and URL")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/regenerate-tags', methods=['POST'])
def regenerate_tags(draft_id):
    """Regenerate tags for a draft using AI."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Use new queue system
        queue_manager_v2 = get_queue_manager_v2()
        
        # Prepare payload
        title = draft.get('title', '')
        age_range = draft.get('age_range', settings.default_age_range)
        reading_level = draft.get('reading_level', settings.default_reading_level)
        author = draft.get('author', '')
        
        payload = {
            'book_id': draft_id,
            'title': title,
            'author': author,
            'age_range': age_range,
            'reading_level': reading_level
        }
        
        # Enqueue task (will automatically delete conflicting tasks)
        task_id = queue_manager_v2.enqueue_task(
            task_type='tags',
            priority=1,
            book_id=draft_id,
            chapter_id=None,
            payload=payload
        )
        
        logger.info(f"Enqueued tag regeneration for draft {draft_id} (task: {task_id})")
        
        return jsonify({
            'success': True,
            'message': 'Tag regeneration started'
        })
    except Exception as e:
        logger.exception("Failed to regenerate tags")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/regenerate-questions', methods=['POST'])
def regenerate_questions(draft_id):
    """Regenerate questions for all chapters in a draft based on current tags."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Check if tags exist
        tags = draft.get('tags', [])
        if not tags:
            return jsonify({
                'error': 'Tags must be set before regenerating questions'
            }), 400
        
        # Extract grade levels from tags
        grade_levels = [tag for tag in tags if tag.startswith('grade-')]
        if not grade_levels:
            return jsonify({
                'error': 'At least one grade tag is required for question generation'
            }), 400
        
        # Get all chapters
        chapters = db.get_draft_chapters(draft_id)
        if not chapters:
            return jsonify({
                'error': 'No chapters found for this draft'
            }), 400
        
        # Use new queue system
        queue_manager_v2 = get_queue_manager_v2()
        
        # Step 1: Delete existing queued question tasks for this draft AND grade levels
        # Only delete tasks for the grade levels we're about to regenerate
        deleted_count = 0
        with queue_manager_v2._get_connection() as conn:
            with conn.cursor() as cur:
                # Use jsonb operator to filter by grade_level in payload
                cur.execute("""
                    DELETE FROM queue_tasks
                    WHERE status = 'queued'
                      AND task_type = 'questions'
                      AND book_id = %s
                      AND payload->>'grade_level' = ANY(%s)
                """, (draft_id, grade_levels))
                deleted_count = cur.rowcount
                conn.commit()
        
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} existing queued question tasks for draft {draft_id} and grades {grade_levels}")
        
        # Step 2: Batch enqueue tasks per chapter
        # Create n_chapters × n_grades × 3 tasks (3 tasks per grade per chapter)
        total_task_count = 0
        for chapter in chapters:
            # Build payloads for all grade levels for this chapter
            # Create 3 separate tasks per grade level (one per question)
            payloads = []
            for grade_level in grade_levels:
                for question_num in range(1, 4):  # 3 questions per grade
                    payload = {
                        'book_id': draft_id,
                        'chapter_id': chapter['id'],
                        'title': draft.get('title', ''),
                        'author': draft.get('author', ''),
                        'chapter_number': chapter['chapter_number'],
                        'chapter_title': chapter['title'],
                        'chapter_text': chapter['content'],
                        'reading_level': draft.get('reading_level', settings.default_reading_level),
                        'age_range': draft.get('age_range', settings.default_age_range),
                        'grade_level': grade_level,
                        'num_questions': 1,  # 1 question per task
                        'vocab_count': 8 if question_num == 1 else 0,  # Only first task generates vocabulary
                        'question_number': question_num
                    }
                    payloads.append(payload)
            
            # Enqueue all tasks for this chapter in one batch
            task_ids = queue_manager_v2.enqueue_tasks_batch(
                task_type='questions',
                priority=3,
                book_id=draft_id,
                chapter_id=chapter['id'],
                payloads=payloads
            )
            total_task_count += len(task_ids)
        
        logger.info(f"Enqueued {total_task_count} question generation tasks for draft {draft_id}")
        
        return jsonify({
            'success': True,
            'message': f'Question regeneration started: {len(chapters)} chapters × {len(grade_levels)} grades = {total_task_count} tasks',
            'deleted_count': deleted_count,
            'created_count': total_task_count
        })
    except Exception as e:
        logger.exception("Failed to start question regeneration")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/tags', methods=['GET'])
def get_draft_tags(draft_id):
    """Get tags for a draft."""
    try:
        db = DatabaseManager()
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        return jsonify({
            'success': True,
            'tags': draft.get('tags', []),
            'tag_status': draft.get('tag_status', 'pending')
        })
    except Exception as e:
        logger.exception("Failed to get tags")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/marker', methods=['PUT'])
def update_marker_position(draft_id):
    """Update the marker position for a draft."""
    try:
        data = request.json
        marker_position = data.get('marker_position')
        
        if marker_position is None:
            return jsonify({'error': 'marker_position is required'}), 400
        
        db = DatabaseManager()
        db.update_draft(draft_id, last_marker_position=marker_position)
        
        return jsonify({
            'success': True,
            'message': 'Marker position saved'
        })
    except Exception as e:
        logger.exception("Failed to update marker position")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/description', methods=['GET'])
def get_draft_description(draft_id):
    """Get description for a draft."""
    try:
        db = DatabaseManager()
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        return jsonify({
            'success': True,
            'description': draft.get('description', ''),
            'description_status': draft.get('description_status', 'pending')
        })
    except Exception as e:
        logger.exception("Failed to get description")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/description', methods=['PUT'])
def update_description(draft_id):
    """Update draft description manually."""
    try:
        data = request.json
        description = data.get('description', '').strip()
        
        db = DatabaseManager()
        
        # Verify draft exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Update description
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_books 
                    SET description = %s, updated_at = NOW()
                    WHERE id = %s
                """, (description, draft_id))
        
        logger.info(f"Updated description for draft {draft_id}")
        
        return jsonify({
            'success': True,
            'message': 'Description updated successfully'
        })
    except Exception as e:
        logger.exception("Failed to update description")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/generate-description', methods=['POST'])
def generate_description(draft_id):
    """Generate a book description using AI, auto-generating synopsis from book content."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Use new queue system
        queue_manager_v2 = get_queue_manager_v2()
        
        # Prepare payload
        title = draft.get('title', '')
        author = draft.get('author', '')
        age_range = draft.get('age_range', settings.default_age_range)
        reading_level = draft.get('reading_level', settings.default_reading_level)
        full_text = draft.get('full_text', '')
        text_sample = ' '.join(full_text.split()[:2000]) if full_text else ''
        
        payload = {
            'book_id': draft_id,
            'title': title,
            'author': author,
            'text_sample': text_sample
        }
        
        # Enqueue task (will automatically delete conflicting tasks)
        task_id = queue_manager_v2.enqueue_task(
            task_type='descriptions',
            priority=2,
            book_id=draft_id,
            chapter_id=None,
            payload=payload
        )
        
        logger.info(f"Enqueued description generation for draft {draft_id} (task: {task_id})")
        
        return jsonify({
            'success': True,
            'message': 'Description generation started'
        })
    except Exception as e:
        logger.exception("Failed to start description generation")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/draft/<draft_id>/usage', methods=['GET'])
def get_text_usage(draft_id):
    """Analyze which parts of the book text have been used in chapters using fuzzy matching."""
    try:
        from rapidfuzz import fuzz
        from rapidfuzz.distance import Levenshtein
        from bs4 import BeautifulSoup
        
        db = DatabaseManager()
        
        # Get the draft
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # CRITICAL: Use full_html to match frontend display, fallback to full_text
        book_text = draft.get('full_html') or draft.get('full_text', '')
        if not book_text:
            return jsonify({'used_paragraphs': []})
        
        # Split book into paragraphs (same way as frontend does)
        book_paragraphs = [p.strip() for p in book_text.split('\n\n') if p.strip()]
        
        logger.info(f"Usage tracking for draft {draft_id}: {len(book_paragraphs)} total paragraphs")
        
        # Get all chapters
        chapters = db.get_draft_chapters(draft_id)
        if not chapters:
            return jsonify({'used_paragraphs': []})
        
        # Track which paragraphs are used and which chapter they belong to
        used_paragraph_indices = set()
        paragraph_to_chapter = {}  # Maps paragraph_index -> chapter_number
        
        # Helper function to normalize text for comparison
        def normalize(text):
            """Normalize text for fuzzy matching - strip HTML, lowercase, remove extra whitespace."""
            # Strip HTML tags using BeautifulSoup
            soup = BeautifulSoup(text, 'html.parser')
            clean_text = soup.get_text(separator=' ')
            # Normalize whitespace and lowercase
            return ' '.join(clean_text.lower().split())
        
        # Normalize paragraphs once (for performance)
        normalized_paragraphs = [normalize(p) for p in book_paragraphs]
        logger.info(f"Normalized {len(normalized_paragraphs)} book paragraphs for matching")
        
        # For each chapter, find matching paragraphs in the book
        for chapter in chapters:
            # Use html_formatting if available (for EPUB books), otherwise use content
            chapter_text = chapter.get('html_formatting') or chapter.get('content', '')
            chapter_number = chapter.get('chapter_number')
            if not chapter_text or chapter_number is None:
                continue
            
            # Normalize the entire chapter as one block for comparison
            # This handles cases where chapters have line breaks mid-sentence
            normalized_full_chapter = normalize(chapter_text)
            
            if not normalized_full_chapter:
                continue
            
            # Also try splitting by double newlines to handle multi-paragraph chapters
            chapter_paragraphs = [p.strip() for p in chapter_text.split('\n\n') if p.strip()]
            normalized_chapter_paras = [normalize(p) for p in chapter_paragraphs if normalize(p)]
            
            # Check each book paragraph against the chapter
            for para_idx, normalized_para in enumerate(normalized_paragraphs):
                if para_idx in used_paragraph_indices:
                    continue  # Already marked as used
                    
                # Skip empty paragraphs
                if not normalized_para:
                    continue
                
                # First, check if this book paragraph is contained in the full chapter
                # This handles chapters that are continuous text with line breaks
                if normalized_para in normalized_full_chapter or normalized_full_chapter in normalized_para:
                    # Use fuzzy matching to confirm
                    leven_sim = Levenshtein.normalized_similarity(normalized_para, normalized_full_chapter) * 100
                    token_sim = fuzz.partial_ratio(normalized_para, normalized_full_chapter)
                    combined_score = (leven_sim * 0.6) + (token_sim * 0.4)
                    
                    if combined_score >= 65:  # Lower threshold for substring matches
                        used_paragraph_indices.add(para_idx)
                        paragraph_to_chapter[para_idx] = chapter_number
                        continue
                
                # Also check against individual chapter paragraphs (for multi-para chapters)
                for chapter_para in normalized_chapter_paras:
                    if not chapter_para:
                        continue
                        
                    # HYBRID APPROACH: Levenshtein + token-based
                    # 1. Normalized Levenshtein similarity (order-aware, edit-tolerant)
                    leven_sim = Levenshtein.normalized_similarity(normalized_para, chapter_para) * 100
                    
                    # 2. Token-based similarity (vocabulary-aware)
                    token_sim = fuzz.token_sort_ratio(normalized_para, chapter_para)
                    
                    # Use weighted average: favor Levenshtein slightly for order preservation
                    # 60% Levenshtein + 40% token = better balance
                    combined_score = (leven_sim * 0.6) + (token_sim * 0.4)
                    
                    # 78% threshold allows minor edits while filtering different text
                    if combined_score >= 78:
                        used_paragraph_indices.add(para_idx)
                        paragraph_to_chapter[para_idx] = chapter_number
                        break  # Found a match, no need to check other chapter paragraphs
        
        return jsonify({
            'used_paragraphs': sorted(list(used_paragraph_indices)),
            'paragraph_chapters': paragraph_to_chapter  # Maps paragraph_index -> chapter_number
        })
        
    except Exception as e:
        logger.exception("Failed to analyze text usage")
        return jsonify({'error': str(e)}), 500


@drafts_bp.route('/finalize-draft/<draft_id>', methods=['POST'])
def finalize_draft(draft_id):
    """Convert a draft to a published book."""
    try:
        db = DatabaseManager()
        
        # Get draft with all chapters
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        chapters_data = db.get_draft_chapters(draft_id)
        
        if not chapters_data:
            return jsonify({'error': 'No chapters found for this draft'}), 400
        
        # Check that all chapters have questions ready
        for ch in chapters_data:
            question_status = get_question_status(ch['id'])
            if question_status != 'ready':
                return jsonify({
                    'error': f"Chapter {ch['chapter_number']} questions not ready (status: {question_status})"
                }), 400
        
        # Create Book object
        total_reading_time = sum(ch.get('estimated_reading_time_minutes', 0) for ch in chapters_data)
        
        book = Book(
            id=uuid4(),
            title=draft.get('title', ''),
            author=draft.get('author', ''),
            description=draft.get('description', ''),
            age_range=draft.get('age_range', settings.default_age_range),
            reading_level=draft.get('reading_level', settings.default_reading_level),
            genre=draft.get('genre', settings.default_genre),
            total_chapters=len(chapters_data),
            estimated_reading_time_minutes=total_reading_time,
            cover_image_url=draft.get('cover_image_url'),
            isbn=None,
            content_rating=None,
            tags=draft.get('tags', [])
        )
        
        # Create Chapter and Question objects
        chapters = []
        questions = []
        
        for ch_data in chapters_data:
            # Fetch full chapter data with questions from database
            full_chapter_data = db.get_draft_chapter(ch_data['id'])
            if not full_chapter_data:
                logger.warning(f"Could not fetch full chapter data for {ch_data['id']}")
                continue
            
            chapter = Chapter(
                id=uuid4(),
                book_id=book.id,
                chapter_number=full_chapter_data['chapter_number'],
                title=full_chapter_data['title'],
                content=full_chapter_data['content'],
                word_count=full_chapter_data['word_count'],
                estimated_reading_time_minutes=full_chapter_data.get('estimated_reading_time_minutes', 0),
                vocabulary_words=full_chapter_data.get('vocabulary', []),
                html_formatting=full_chapter_data.get('html_formatting', full_chapter_data['content'])
            )
            chapters.append(chapter)
            
            # Get questions for this chapter from database
            ch_questions = full_chapter_data.get('questions', [])
            for q_data in ch_questions:
                question = Question(
                    id=uuid4(),
                    book_id=book.id,
                    chapter_id=chapter.id,
                    question_text=q_data['question_text'],
                    question_type=q_data.get('question_type', 'comprehension'),
                    difficulty_level=q_data.get('difficulty_level', 'medium'),
                    expected_keywords=q_data.get('expected_keywords', []),
                    min_word_count=q_data.get('min_word_count', settings.min_answer_words),
                    max_word_count=q_data.get('max_word_count', settings.max_answer_words),
                    order_index=q_data.get('order_index', 1),
                    grade_level=q_data.get('grade_level')
                )
                questions.append(question)
        
        # Create ProcessedBook
        processed_book = ProcessedBook(
            book=book,
            chapters=chapters,
            questions=questions
        )
        
        # Insert into database
        book_id_str, num_chapters, num_questions = db.insert_processed_book(processed_book)
        
        # Delete the draft
        db.delete_draft(draft_id)
        
        logger.info(f"Finalized draft {draft_id} -> book {book_id_str}")
        
        return jsonify({
            'success': True,
            'book_id': book_id_str,
            'chapters': num_chapters,
            'questions': num_questions
        })
    except Exception as e:
        logger.exception("Failed to finalize draft")
        return jsonify({'error': str(e)}), 500
