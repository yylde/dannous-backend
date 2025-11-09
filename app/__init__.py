"""Flask application factory."""

import os
import logging
import atexit
from flask import Flask
from flask_cors import CORS
from pathlib import Path

from src.ollama_queue import shutdown_queue_manager, get_queue_manager
from src.queue_manager_v2 import get_queue_manager_v2
from src.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create download directory
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Control parallel vs sequential question generation
PARALLEL_GENERATION = os.environ.get('PARALLEL_GENERATION', 'true').lower() == 'true'


def cleanup_queue():
    """Cleanup queue managers on shutdown."""
    logger.info("Shutting down queue managers...")
    shutdown_queue_manager(wait=True, timeout=30.0)
    
    try:
        queue_v2 = get_queue_manager_v2()
        queue_v2.shutdown()
    except Exception as e:
        logger.warning(f"Error shutting down QueueManagerV2: {e}")


def create_app():
    """Application factory for Flask app."""
    # Flask app created in app package, but templates and static are in parent directory
    import os
    template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
    
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    CORS(app)
    
    # Store configuration
    app.config['DOWNLOAD_DIR'] = DOWNLOAD_DIR
    app.config['PARALLEL_GENERATION'] = PARALLEL_GENERATION
    
    logger.info(f"Question generation mode: {'PARALLEL' if PARALLEL_GENERATION else 'SEQUENTIAL'}")
    
    # Initialize old queue manager with database persistence (legacy)
    queue_manager = get_queue_manager()
    queue_manager._database_url = settings.database_url
    
    # Load any pending tasks from previous session
    pending_tasks = queue_manager.load_persistent_tasks()
    if pending_tasks:
        logger.info(f"Loaded {len(pending_tasks)} pending tasks from database")
    
    # Initialize new QueueManagerV2 and start workers
    logger.info("Initializing QueueManagerV2...")
    queue_v2 = get_queue_manager_v2()
    queue_v2.start()
    logger.info("✓ QueueManagerV2 worker and watchdog started")
    
    # Register blueprints
    from app.routes.ui import ui_bp
    from app.routes.downloads import downloads_bp
    from app.routes.drafts import drafts_bp
    from app.routes.chapters import chapters_bp
    from app.routes.queue import queue_bp
    from app.routes.questions import questions_bp
    
    app.register_blueprint(ui_bp)
    app.register_blueprint(downloads_bp, url_prefix='/api')
    app.register_blueprint(drafts_bp, url_prefix='/api')
    app.register_blueprint(chapters_bp, url_prefix='/api')
    app.register_blueprint(queue_bp, url_prefix='/api')
    app.register_blueprint(questions_bp, url_prefix='/api')
    
    # Register cleanup handler
    atexit.register(cleanup_queue)
    
    # Start the question generation watcher thread
    from app.tasks.question_tasks import start_question_generation_watcher
    start_question_generation_watcher()
    
    return app
