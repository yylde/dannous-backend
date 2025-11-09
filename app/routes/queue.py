"""Routes for queue monitoring and management."""

import logging
from flask import Blueprint, jsonify

queue_bp = Blueprint('queue', __name__)
logger = logging.getLogger(__name__)


@queue_bp.route('/queue/status', methods=['GET'])
def get_queue_status():
    """Get current status of the Ollama queue."""
    try:
        from src.ollama_queue import get_queue_manager
        manager = get_queue_manager()
        queue_info = manager.get_queue_info()
        
        return jsonify({
            'success': True,
            'queue': queue_info
        })
    except Exception as e:
        logger.exception("Failed to get queue status")
        return jsonify({'error': str(e)}), 500


@queue_bp.route('/queue/flush', methods=['POST'])
def flush_queue():
    """Flush all pending tasks from the Ollama queue."""
    try:
        from src.ollama_queue import get_queue_manager
        manager = get_queue_manager()
        flushed_count = manager.flush_queue()
        
        logger.info(f"Queue flushed: {flushed_count} tasks removed")
        
        return jsonify({
            'success': True,
            'flushed_count': flushed_count,
            'message': f'Flushed {flushed_count} tasks from queue'
        })
    except Exception as e:
        logger.exception("Failed to flush queue")
        return jsonify({'error': str(e)}), 500
