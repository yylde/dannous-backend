#!/usr/bin/env python3
"""Flask application entry point."""

from app import create_app

app = create_app()

if __name__ == '__main__':
    # Disable reloader to prevent duplicate queue workers
    # The reloader creates a parent and child process, causing:
    # - Two QueueManagerV2 workers racing for tasks
    # - Two watchdog threads
    # With use_reloader=False, you must manually restart after code changes
    app.run(host='0.0.0.0', port=5002, debug=True, use_reloader=False)
