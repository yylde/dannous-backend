"""Routes for question and vocabulary CRUD operations."""

import logging
from flask import Blueprint, request, jsonify
from src.database import DatabaseManager

questions_bp = Blueprint('questions', __name__)
logger = logging.getLogger(__name__)


@questions_bp.route('/question/<question_id>', methods=['PUT'])
def update_question(question_id):
    """Update a draft question."""
    try:
        data = request.json
        db = DatabaseManager()
        db.update_question(
            question_id,
            data.get('question_text'),
            data.get('question_type'),
            data.get('difficulty_level'),
            data.get('expected_keywords', []),
            data.get('min_word_count'),
            data.get('max_word_count')
        )
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to update question")
        return jsonify({'error': str(e)}), 500


@questions_bp.route('/question/<question_id>', methods=['DELETE'])
def delete_question(question_id):
    """Delete a draft question."""
    try:
        db = DatabaseManager()
        db.delete_question(question_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to delete question")
        return jsonify({'error': str(e)}), 500


@questions_bp.route('/vocabulary/<vocab_id>', methods=['PUT'])
def update_vocabulary(vocab_id):
    """Update a draft vocabulary item."""
    try:
        data = request.json
        db = DatabaseManager()
        db.update_vocabulary(
            vocab_id,
            data.get('word'),
            data.get('definition'),
            data.get('example', '')
        )
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to update vocabulary")
        return jsonify({'error': str(e)}), 500


@questions_bp.route('/vocabulary/<vocab_id>', methods=['DELETE'])
def delete_vocabulary(vocab_id):
    """Delete a draft vocabulary item."""
    try:
        db = DatabaseManager()
        db.delete_vocabulary(vocab_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to delete vocabulary")
        return jsonify({'error': str(e)}), 500
