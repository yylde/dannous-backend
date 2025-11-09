"""UI routes for rendering HTML pages."""

from flask import Blueprint, render_template

ui_bp = Blueprint('ui', __name__)


@ui_bp.route('/')
def index():
    """Admin UI homepage."""
    return render_template('index.html')


@ui_bp.route('/queue')
def queue_page():
    """Queue monitoring page."""
    return render_template('queue.html')
