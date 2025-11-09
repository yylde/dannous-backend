"""Routes for chapter management."""

import logging
import threading
from flask import Blueprint, request, jsonify

from src.database import DatabaseManager
from app.tasks.question_tasks import regenerate_single_chapter_questions_async

chapters_bp = Blueprint('chapters', __name__)
logger = logging.getLogger(__name__)


@chapters_bp.route('/draft-chapter', methods=['POST'])
def save_draft_chapter():
    """Save a chapter to draft. Auto-triggers question generation if tags are ready."""
    try:
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
        
        # Check if tags are ready and auto-trigger question generation
        draft = db.get_draft(draft_id)
        if draft and draft.get('tag_status') == 'ready':
            tags = draft.get('tags', [])
            grade_tags = [tag for tag in tags if tag.startswith('grade-')]
            
            if grade_tags:
                logger.info(f"Tags are ready for draft {draft_id}. Auto-triggering question generation for chapter {chapter_id}")
                
                # Trigger async question generation for this chapter
                regen_thread = threading.Thread(
                    target=regenerate_single_chapter_questions_async,
                    args=(
                        chapter_id,
                        draft_id,
                        title,
                        content,
                        html_content,
                        draft.get('age_range'),
                        draft.get('reading_level')
                    )
                )
                regen_thread.daemon = True
                regen_thread.start()
                
                return jsonify({
                    'success': True,
                    'chapter_id': chapter_id,
                    'status': 'generating'  # Question generation started
                })
            else:
                logger.warning(f"Draft {draft_id} has tags but no grade tags found")
        
        # Tags not ready yet - watcher will handle it later
        return jsonify({
            'success': True,
            'chapter_id': chapter_id,
            'status': 'pending'  # Waiting for tags
        })
    
    except Exception as e:
        logger.exception("Failed to save draft chapter")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/draft-chapters/<draft_id>', methods=['GET'])
def get_draft_chapters_status(draft_id):
    """Get all chapters for a draft with their current status (for polling)."""
    try:
        db = DatabaseManager()
        chapters = db.get_draft_chapters(draft_id)
        
        # Return only the data needed for status polling
        chapter_statuses = [
            {
                'id': ch['id'],
                'question_status': ch.get('question_status', 'pending')
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
        db = DatabaseManager()
        chapter = db.get_draft_chapter(chapter_id)
        if not chapter:
            return jsonify({'error': 'Chapter not found'}), 404
        
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
    """Regenerate questions for a single chapter (simplified route)."""
    try:
        db = DatabaseManager()
        
        # Get the chapter to verify it exists and get its draft_id
        chapter = db.get_draft_chapter(chapter_id)
        if not chapter:
            return jsonify({'error': 'Chapter not found'}), 404
        
        draft_id = chapter.get('draft_id')
        if not draft_id:
            return jsonify({'error': 'Chapter not associated with a draft'}), 404
        
        # Get the draft to verify tags are ready
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        tag_status = draft.get('tag_status')
        if tag_status != 'ready':
            return jsonify({
                'error': f'Tags must be ready before regenerating questions. Current status: {tag_status}'
            }), 400
        
        # Trigger async regeneration for single chapter
        regen_thread = threading.Thread(
            target=regenerate_single_chapter_questions_async,
            args=(
                chapter_id,
                draft_id,
                chapter['title'],
                chapter['content'],
                chapter.get('html_formatting'),
                draft.get('age_range'),
                draft.get('reading_level')
            )
        )
        regen_thread.daemon = True
        regen_thread.start()
        
        logger.info(f"Started question regeneration for chapter {chapter_id}")
        
        return jsonify({
            'success': True,
            'message': 'Question regeneration started for chapter'
        })
    except Exception as e:
        logger.exception("Failed to start chapter question regeneration")
        return jsonify({'error': str(e)}), 500


@chapters_bp.route('/draft/<draft_id>/regenerate-chapter-questions/<chapter_id>', methods=['POST'])
def regenerate_chapter_questions(draft_id, chapter_id):
    """Regenerate questions for a single chapter."""
    try:
        db = DatabaseManager()
        
        # Get the chapter to verify it exists
        chapter = db.get_draft_chapter(chapter_id)
        if not chapter:
            return jsonify({'error': 'Chapter not found'}), 404
        
        # Get the draft to verify tags are ready
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        tag_status = draft.get('tag_status')
        if tag_status != 'ready':
            return jsonify({
                'error': f'Tags must be ready before regenerating questions. Current status: {tag_status}'
            }), 400
        
        # Trigger async regeneration for single chapter
        regen_thread = threading.Thread(
            target=regenerate_single_chapter_questions_async,
            args=(
                chapter_id,
                draft_id,
                chapter['title'],
                chapter['content'],
                chapter.get('html_formatting'),
                draft.get('age_range'),
                draft.get('reading_level')
            )
        )
        regen_thread.daemon = True
        regen_thread.start()
        
        logger.info(f"Started question regeneration for chapter {chapter_id}")
        
        return jsonify({
            'success': True,
            'message': 'Question regeneration started for chapter'
        })
    except Exception as e:
        logger.exception("Failed to start chapter question regeneration")
        return jsonify({'error': str(e)}), 500
