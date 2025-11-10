"""Routes for queue monitoring and management (V2)."""

import logging
from flask import Blueprint, jsonify, request

queue_bp = Blueprint('queue', __name__)
logger = logging.getLogger(__name__)


@queue_bp.route('/api/queue/status', methods=['GET'])
def get_queue_status():
    """Get current status of the queue (V2)."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        manager = get_queue_manager_v2()
        status = manager.get_status()
        
        return jsonify({
            'success': True,
            'status': status
        })
    except Exception as e:
        logger.exception("Failed to get queue status")
        return jsonify({'error': str(e)}), 500


@queue_bp.route('/api/queue/enqueue', methods=['POST'])
def enqueue_task():
    """Enqueue a new task."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        required_fields = ['task_type', 'priority', 'book_id', 'payload']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        manager = get_queue_manager_v2()
        task_id = manager.enqueue_task(
            task_type=data['task_type'],
            priority=data['priority'],
            book_id=data['book_id'],
            chapter_id=data.get('chapter_id'),
            payload=data['payload']
        )
        
        logger.info(f"Enqueued task: {task_id} [{data['task_type']}]")
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': f"Task {task_id} enqueued"
        })
    except Exception as e:
        logger.exception("Failed to enqueue task")
        return jsonify({'error': str(e)}), 500


@queue_bp.route('/api/queue/clear', methods=['DELETE'])
def clear_all_tasks():
    """Clear ALL tasks from the queue regardless of status."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        manager = get_queue_manager_v2()
        deleted_count = manager.clear_all_tasks()
        
        logger.info(f"Cleared ALL {deleted_count} tasks from queue")
        
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'message': f'Cleared {deleted_count} tasks from queue'
        })
    except Exception as e:
        logger.exception("Failed to clear queue")
        return jsonify({'error': str(e)}), 500


@queue_bp.route('/queue/status', methods=['GET'])
def get_queue_status_legacy():
    """Legacy endpoint - redirects to new endpoint."""
    return get_queue_status()


@queue_bp.route('/queue/flush', methods=['POST'])
def flush_queue():
    """Flush all tasks (legacy endpoint)."""
    try:
        from src.queue_manager_v2 import get_queue_manager_v2
        manager = get_queue_manager_v2()
        deleted_count = manager.clear_all_tasks()
        
        logger.info(f"Queue flushed: {deleted_count} tasks removed")
        
        return jsonify({
            'success': True,
            'flushed_count': deleted_count,
            'message': f'Flushed {deleted_count} tasks from queue'
        })
    except Exception as e:
        logger.exception("Failed to flush queue")
        return jsonify({'error': str(e)}), 500
