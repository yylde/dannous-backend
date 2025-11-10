"""Routes for chapter management."""

import logging
import threading
from flask import Blueprint, request, jsonify

from src.database import DatabaseManager
from app.tasks.question_tasks import regenerate_single_chapter_questions_async
from src.status_calculator import get_question_status

chapters_bp = Blueprint('chapters', __name__)
logger = logging.getLogger(__name__)


@chapters_bp.route('/draft-chapter', methods=['POST'])
def save_draft_chapter():
    """Save a chapter to draft. Auto-triggers question generation if tags are ready."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        from src.config import settings
        
        data = request.json
        draft_id = data.get('draft_id')
        chapter_number = data.get('chapter_number')
        title = data.get('title')
        content = data.get('content')
        html_content = data.get('html_content')
        word_count = data.get('word_count')
        
        if not all([draft_id, chapter_number, title, content]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        db = DatabaseManager()
        chapter_id = db.save_draft_chapter(
            draft_id=draft_id,
            chapter_number=chapter_number,
            title=title,
            content=content,
            word_count=word_count,
            html_formatting=html_content
        )
        
        logger.info(f"Saved chapter {chapter_id} for draft {draft_id}.")
        
        # Check if tags exist and auto-enqueue question generation
        draft = db.get_draft(draft_id)
        if draft:
            tags = draft.get('tags', [])
            grade_tags = [tag for tag in tags if tag.startswith('grade-')]
            
            if grade_tags:
                logger.info(f"Tags exist for draft {draft_id}. Auto-enqueuing question generation for chapter {chapter_id}")
                
                # Build all payloads first
                payloads = []
                for grade_level in grade_tags:
                    payload = {
                        'book_id': draft_id,
                        'chapter_id': chapter_id,
                        'title': draft.get('title', ''),
                        'author': draft.get('author', ''),
                        'chapter_number': chapter_number,
                        'chapter_title': title,
                        'chapter_text': content,
                        'reading_level': draft.get('reading_level', settings.default_reading_level),
                        'age_range': draft.get('age_range', settings.default_age_range),
                        'grade_level': grade_level,
                        'num_questions': 3,
                        'vocab_count': 8
                    }
                    payloads.append(payload)
                
                # Batch enqueue all tasks at once
                queue_manager_v2 = get_queue_manager_v2()
                task_ids = queue_manager_v2.enqueue_tasks_batch(
                    task_type='questions',
                    priority=3,
                    book_id=draft_id,
                    chapter_id=chapter_id,
                    payloads=payloads
                )
                
                logger.info(f"Enqueued {len(task_ids)} question generation tasks for chapter {chapter_id}")
                
                return jsonify({
                    'success': True,
                    'chapter_id': chapter_id,
                    'status': 'queued',
                    'tasks_enqueued': len(task_ids)
                })
            else:
                logger.info(f"Draft {draft_id} has no grade tags yet")
        
        # Tags not ready yet
        return jsonify({
            'success': True,
            'chapter_id': chapter_id,
            'status': 'pending'
        })
    
    except Exception as e:
        logger.exception("Failed to save draft chapter")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/draft-chapters/<draft_id>', methods=['GET'])
def get_draft_chapters_status(draft_id):
    """Get all chapters for a draft with their current status (for polling)."""
    try:
        from src.status_calculator import get_question_status
        
        db = DatabaseManager()
        chapters = db.get_draft_chapters(draft_id)
        
        # Return only the data needed for status polling with calculated status
        chapter_statuses = [
            {
                'id': ch['id'],
                'question_status': get_question_status(ch['id'])
            }
            for ch in chapters
        ]
        
        return jsonify({'success': True, 'chapters': chapter_statuses})
    except Exception as e:
        logger.exception("Failed to get draft chapters status")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/draft-chapter/<chapter_id>', methods=['GET'])
def get_draft_chapter_detail(chapter_id):
    """Get chapter details with questions and vocabulary."""
    try:
        from src.status_calculator import get_question_status
        
        db = DatabaseManager()
        chapter = db.get_draft_chapter(chapter_id)
        if not chapter:
            return jsonify({'error': 'Chapter not found'}), 404
        
        # Add calculated status
        chapter['question_status'] = get_question_status(chapter_id)
        
        return jsonify({'success': True, 'chapter': chapter})
    except Exception as e:
        logger.exception("Failed to get chapter details")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/draft-chapter/<chapter_id>', methods=['DELETE'])
def delete_draft_chapter(chapter_id):
    """Delete a draft chapter."""
    try:
        db = DatabaseManager()
        deleted_data = db.delete_draft_chapter(chapter_id)
        if not deleted_data:
            return jsonify({'error': 'Chapter not found'}), 404
        
        return jsonify({
            'success': True,
            'content': deleted_data['content'],
            'chapter_number': deleted_data['chapter_number']
        })
    except Exception as e:
        logger.exception("Failed to delete chapter")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/chapter/<chapter_id>', methods=['PUT'])
def update_chapter(chapter_id):
    """Update a draft chapter's content and HTML."""
    try:
        data = request.json
        db = DatabaseManager()
        
        success = db.update_draft_chapter(
            chapter_id,
            title=data.get('title'),
            content=data.get('content'),
            html_formatting=data.get('html_formatting')
        )
        
        if not success:
            return jsonify({'error': 'Chapter not found or no changes made'}), 404
        
        return jsonify({'success': True, 'message': 'Chapter updated successfully'})
    except Exception as e:
        logger.exception("Failed to update chapter")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/chapter/<chapter_id>/regenerate-questions', methods=['POST'])
def regenerate_chapter_questions_simple(chapter_id):
    """Regenerate questions for a single chapter using queue system."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        from src.config import settings
        
        db = DatabaseManager()
        
        # Get the chapter to verify it exists and get its draft_id
        chapter = db.get_draft_chapter(chapter_id)
        if not chapter:
            return jsonify({'error': 'Chapter not found'}), 404
        
        draft_id = chapter.get('draft_id')
        if not draft_id:
            return jsonify({'error': 'Chapter not associated with a draft'}), 404
        
        # Get the draft to get tags
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Check if tags exist (don't require them to be 'ready', just need to exist)
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
        
        # Use new queue system
        queue_manager_v2 = get_queue_manager_v2()
        
        # Step 1: Delete existing queued question tasks for this chapter AND grade levels
        # Only delete tasks for the grade levels we're about to regenerate
        deleted_count = 0
        with queue_manager_v2._get_connection() as conn:
            with conn.cursor() as cur:
                # Use jsonb operator to filter by grade_level in payload
                cur.execute("""
                    DELETE FROM queue_tasks
                    WHERE status = 'queued'
                      AND task_type = 'questions'
                      AND chapter_id = %s
                      AND payload->>'grade_level' = ANY(%s)
                """, (chapter_id, grade_levels))
                deleted_count = cur.rowcount
                conn.commit()
        
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} existing queued question tasks for chapter {chapter_id} and grades {grade_levels}")
        
        # Step 2: Create 3 tasks per grade level (same as draft-level regenerate)
        payloads = []
        for grade_level in grade_levels:
            for question_num in range(1, 4):  # 3 questions per grade
                payload = {
                    'book_id': draft_id,
                    'chapter_id': chapter_id,
                    'title': draft.get('title', ''),
                    'author': draft.get('author', ''),
                    'chapter_number': chapter.get('chapter_number'),
                    'chapter_title': chapter.get('title'),
                    'chapter_text': chapter.get('content'),
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
            chapter_id=chapter_id,
            payloads=payloads
        )
        
        logger.info(f"Enqueued {len(task_ids)} question generation tasks for chapter {chapter_id}")
        
        return jsonify({
            'success': True,
            'message': f'Question regeneration started: {len(grade_levels)} grades × 3 questions = {len(task_ids)} tasks',
            'deleted_count': deleted_count,
            'created_count': len(task_ids)
        })
    except Exception as e:
        logger.exception("Failed to start chapter question regeneration")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/draft/<draft_id>/regenerate-chapter-questions/<chapter_id>', methods=['POST'])
def regenerate_chapter_questions(draft_id, chapter_id):
    """Regenerate questions for a single chapter using queue system."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        from src.config import settings
        
        db = DatabaseManager()
        
        # Get the chapter to verify it exists
        chapter = db.get_draft_chapter(chapter_id)
        if not chapter:
            return jsonify({'error': 'Chapter not found'}), 404
        
        # Get the draft to get tags
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Check if tags exist (don't require them to be 'ready', just need to exist)
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
        
        # Use new queue system
        queue_manager_v2 = get_queue_manager_v2()
        
        # Step 1: Delete existing queued question tasks for this chapter AND grade levels
        # Only delete tasks for the grade levels we're about to regenerate
        deleted_count = 0
        with queue_manager_v2._get_connection() as conn:
            with conn.cursor() as cur:
                # Use jsonb operator to filter by grade_level in payload
                cur.execute("""
                    DELETE FROM queue_tasks
                    WHERE status = 'queued'
                      AND task_type = 'questions'
                      AND chapter_id = %s
                      AND payload->>'grade_level' = ANY(%s)
                """, (chapter_id, grade_levels))
                deleted_count = cur.rowcount
                conn.commit()
        
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} existing queued question tasks for chapter {chapter_id} and grades {grade_levels}")
        
        # Step 2: Create 3 tasks per grade level (same as draft-level regenerate)
        payloads = []
        for grade_level in grade_levels:
            for question_num in range(1, 4):  # 3 questions per grade
                payload = {
                    'book_id': draft_id,
                    'chapter_id': chapter_id,
                    'title': draft.get('title', ''),
                    'author': draft.get('author', ''),
                    'chapter_number': chapter.get('chapter_number'),
                    'chapter_title': chapter.get('title'),
                    'chapter_text': chapter.get('content'),
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
            chapter_id=chapter_id,
            payloads=payloads
        )
        
        logger.info(f"Enqueued {len(task_ids)} question generation tasks for chapter {chapter_id}")
        
        return jsonify({
            'success': True,
            'message': f'Question regeneration started: {len(grade_levels)} grades × 3 questions = {len(task_ids)} tasks',
            'deleted_count': deleted_count,
            'created_count': len(task_ids)
        })
    except Exception as e:
        logger.exception("Failed to start chapter question regeneration")
        return jsonify({'error': str(e)}), 500
