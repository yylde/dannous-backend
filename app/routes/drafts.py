"""Routes for draft book management."""

import logging
import threading
from flask import Blueprint, request, jsonify
from uuid import uuid4

from src.database import DatabaseManager
from src.models import Book, Chapter, Question, ProcessedBook
from src.config import settings
from src.chapter_splitter import calculate_reading_time
from app.tasks.tag_tasks import generate_tags_async
from app.tasks.description_tasks import generate_description_async
from app.tasks.question_tasks import regenerate_questions_for_draft_async

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
        db = DatabaseManager()
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        chapters = db.get_draft_chapters(draft_id)
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
            # Safe to start async operations
            logger.info(f"Created draft {draft_id}, starting async tag and description generation...")
            
            # Trigger async tag generation in background thread
            # Transaction is guaranteed committed since db object is out of scope
            tag_thread = threading.Thread(
                target=generate_tags_async,
                args=(
                    draft_id,
                    data.get('title'),
                    data.get('author'),
                    data.get('age_range', settings.default_age_range),
                    data.get('reading_level', settings.default_reading_level)
                )
            )
            tag_thread.daemon = True
            tag_thread.start()
            
            logger.info(f"Started async tag generation for draft {draft_id}")
            
            # Trigger async description generation in background thread
            book_text_sample = ' '.join(full_text.split()[:2000]) if full_text else ''
            description_thread = threading.Thread(
                target=generate_description_async,
                args=(
                    draft_id,
                    data.get('title'),
                    data.get('author'),
                    book_text_sample
                )
            )
            description_thread.daemon = True
            description_thread.start()
            
            logger.info(f"Started async description generation for draft {draft_id}")
            
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
        from datetime import datetime, timedelta
        
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Check if tag generation is already in progress
        current_tag_status = draft.get('tag_status')
        force = request.json.get('force', False) if request.json else False
        
        if current_tag_status in ('pending', 'generating') and not force:
            # Check if it's been stuck for more than 10 minutes
            updated_at = draft.get('updated_at')
            if updated_at:
                # Parse the datetime (it comes as a string from the database)
                if isinstance(updated_at, str):
                    from dateutil import parser
                    updated_at = parser.parse(updated_at)
                
                time_since_update = datetime.now(updated_at.tzinfo) - updated_at
                
                # If it's been generating for more than 10 minutes, consider it stuck
                if time_since_update > timedelta(minutes=10):
                    logger.warning(f"Tag status stuck in '{current_tag_status}' for {time_since_update}. Allowing regeneration.")
                else:
                    logger.info(f"Blocked duplicate tag regeneration request for draft {draft_id} (current status: {current_tag_status})")
                    return jsonify({
                        'error': 'Tag generation already in progress. Please wait for it to complete or try again in a few minutes.'
                    }), 409
            else:
                # No timestamp, block to be safe
                logger.info(f"Blocked duplicate tag regeneration request for draft {draft_id} (current status: {current_tag_status})")
                return jsonify({
                    'error': 'Tag generation already in progress. Please wait for it to complete.'
                }), 409
        
        # Set tag status to pending
        db.update_draft_tag_status(draft_id, 'pending')
        
        # Trigger async tag generation
        tag_thread = threading.Thread(
            target=generate_tags_async,
            args=(
                draft_id,
                draft.get('title'),
                draft.get('author'),
                draft.get('age_range', settings.default_age_range),
                draft.get('reading_level', settings.default_reading_level)
            )
        )
        tag_thread.daemon = True
        tag_thread.start()
        
        logger.info(f"Started tag regeneration for draft {draft_id}")
        
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
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Check if tag status is ready
        tag_status = draft.get('tag_status')
        if tag_status != 'ready':
            return jsonify({
                'error': f'Tags must be ready before regenerating questions. Current status: {tag_status}'
            }), 400
        
        # Trigger async regeneration
        regen_thread = threading.Thread(
            target=regenerate_questions_for_draft_async,
            args=(draft_id,)
        )
        regen_thread.daemon = True
        regen_thread.start()
        
        logger.info(f"Started question regeneration for draft {draft_id}")
        
        return jsonify({
            'success': True,
            'message': 'Question regeneration started for all chapters'
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


@drafts_bp.route('/draft/<draft_id>/usage', methods=['GET'])
def get_draft_usage(draft_id):
    """Get paragraph usage statistics for a draft."""
    try:
        db = DatabaseManager()
        usage = db.get_draft_usage(draft_id)
        
        if usage is None:
            return jsonify({'error': 'Draft not found'}), 404
        
        return jsonify({
            'success': True,
            'used_paragraphs': usage['used_paragraphs'],
            'paragraph_chapters': usage['paragraph_chapters']
        })
    except Exception as e:
        logger.exception("Failed to get usage")
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
            if ch.get('question_status') != 'ready':
                return jsonify({
                    'error': f"Chapter {ch['chapter_number']} questions not ready (status: {ch.get('question_status')})"
                }), 400
        
        # Create Book object
        total_reading_time = sum(ch.get('estimated_reading_time_minutes', 0) for ch in chapters_data)
        
        book = Book(
            id=uuid4(),
            title=draft['title'],
            author=draft['author'],
            description=draft.get('description', ''),
            age_range=draft['age_range'],
            reading_level=draft['reading_level'],
            genre=draft.get('genre', settings.default_genre),
            total_chapters=len(chapters_data),
            estimated_reading_time_minutes=total_reading_time,
            cover_image_url=draft.get('cover_image_url'),
            tags=draft.get('tags', [])
        )
        
        # Create Chapter and Question objects
        chapters = []
        questions = []
        
        for ch_data in chapters_data:
            chapter = Chapter(
                id=uuid4(),
                book_id=book.id,
                chapter_number=ch_data['chapter_number'],
                title=ch_data['title'],
                content=ch_data['content'],
                word_count=ch_data['word_count'],
                estimated_reading_time_minutes=ch_data.get('estimated_reading_time_minutes', 0),
                vocabulary_words=ch_data.get('vocabulary_words', []),
                html_formatting=ch_data.get('html_formatting', ch_data['content'])
            )
            chapters.append(chapter)
            
            # Get questions for this chapter
            ch_questions = ch_data.get('questions', [])
            for i, q_data in enumerate(ch_questions, 1):
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
                    order_index=i,
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
