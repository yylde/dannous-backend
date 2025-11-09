"""Database-driven queue manager (V2).

This queue manager uses PostgreSQL for persistence and atomic task locking.
Workers call Ollama DIRECTLY without nested queueing.
"""

import logging
import time
import threading
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

from src.config import settings
from src.queue_executors import (
    execute_tag_generation,
    execute_description_generation,
    execute_question_generation
)

logger = logging.getLogger(__name__)


@dataclass
class QueueTask:
    """Represents a queue task from the database."""
    id: str
    task_type: str
    priority: int
    status: str
    book_id: str
    chapter_id: Optional[str]
    payload: Dict[str, Any]
    attempts: int
    created_at: datetime


class QueueManagerV2:
    """
    Database-driven queue manager with atomic task locking.
    
    Features:
    - PostgreSQL-backed persistence
    - Atomic task locking with SELECT FOR UPDATE SKIP LOCKED
    - Automatic timeout handling (15 minutes)
    - CASCADE deletion when books/chapters are deleted
    - Workers call Ollama directly (no nested queueing)
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize queue manager."""
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.database_url = database_url or settings.database_url
        self._shutdown = False
        self._worker_thread = None
        self._watchdog_thread = None
        
        logger.info("QueueManagerV2 initialized")
    
    def _get_connection(self):
        """Get database connection."""
        return psycopg2.connect(self.database_url)
    
    def enqueue_task(
        self,
        task_type: str,
        priority: int,
        book_id: str,
        chapter_id: Optional[str],
        payload: Dict[str, Any]
    ) -> str:
        """
        Enqueue a task after deleting conflicting tasks.
        
        Args:
            task_type: Type of task ('tags', 'descriptions', 'questions')
            priority: Priority level (1=high, 2=medium, 3=low)
            book_id: Draft book ID
            chapter_id: Chapter ID (None for book-level tasks)
            payload: Task parameters as dict
        
        Returns:
            Task ID (UUID)
        """
        # Delete conflicting tasks first
        self.delete_conflicting_tasks(task_type, book_id, chapter_id)
        
        # Insert new task
        timeout_minutes = 15
        timeout_at = datetime.now() + timedelta(minutes=timeout_minutes)
        
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO queue_tasks (
                        task_type, priority, status, book_id, chapter_id, 
                        payload, timeout_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    task_type,
                    priority,
                    'queued',
                    book_id,
                    chapter_id,
                    json.dumps(payload),
                    timeout_at
                ))
                task_id = cur.fetchone()[0]
                conn.commit()
        
        logger.info(f"[QUEUE] Enqueued {task_type} task: {task_id} (priority={priority})")
        return str(task_id)
    
    def delete_conflicting_tasks(
        self,
        task_type: str,
        book_id: str,
        chapter_id: Optional[str]
    ) -> int:
        """
        Delete conflicting queued tasks.
        
        Args:
            task_type: Type of task
            book_id: Draft book ID
            chapter_id: Chapter ID (None for book-level tasks)
        
        Returns:
            Number of tasks deleted
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                if chapter_id:
                    cur.execute("""
                        DELETE FROM queue_tasks
                        WHERE status = 'queued'
                          AND task_type = %s
                          AND book_id = %s
                          AND chapter_id = %s
                    """, (task_type, book_id, chapter_id))
                else:
                    cur.execute("""
                        DELETE FROM queue_tasks
                        WHERE status = 'queued'
                          AND task_type = %s
                          AND book_id = %s
                          AND chapter_id IS NULL
                    """, (task_type, book_id))
                
                deleted_count = cur.rowcount
                conn.commit()
        
        if deleted_count > 0:
            logger.info(f"[QUEUE] Deleted {deleted_count} conflicting {task_type} tasks")
        
        return deleted_count
    
    def _lock_next_task(self) -> Optional[QueueTask]:
        """
        Atomically lock the next available task.
        
        Uses SELECT FOR UPDATE SKIP LOCKED for atomic locking.
        
        Returns:
            QueueTask if available, None otherwise
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Atomically select and lock next task
                    cur.execute("""
                        SELECT id, task_type, priority, status, book_id, chapter_id,
                               payload, attempts, created_at
                        FROM queue_tasks
                        WHERE status = 'queued'
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    """)
                    
                    row = cur.fetchone()
                    if not row:
                        return None
                    
                    # Update to processing status
                    task_id = row['id']
                    timeout_at = datetime.now() + timedelta(minutes=15)
                    
                    cur.execute("""
                        UPDATE queue_tasks
                        SET status = 'processing',
                            locked_at = NOW(),
                            started_at = NOW(),
                            timeout_at = %s,
                            attempts = attempts + 1
                        WHERE id = %s
                    """, (timeout_at, task_id))
                    
                    conn.commit()
                    
                    # Convert to QueueTask
                    task = QueueTask(
                        id=str(row['id']),
                        task_type=row['task_type'],
                        priority=row['priority'],
                        status='processing',
                        book_id=str(row['book_id']),
                        chapter_id=str(row['chapter_id']) if row['chapter_id'] else None,
                        payload=row['payload'],
                        attempts=row['attempts'] + 1,
                        created_at=row['created_at']
                    )
                    
                    return task
        
        except Exception as e:
            logger.error(f"[QUEUE] Error locking task: {e}")
            return None
    
    def _update_task_status(
        self,
        task_id: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """
        Update task status.
        
        Args:
            task_id: Task ID
            status: New status ('ready', 'error')
            error_message: Error message if status is 'error'
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                if status == 'ready':
                    cur.execute("""
                        UPDATE queue_tasks
                        SET status = %s,
                            completed_at = NOW(),
                            error_message = NULL
                        WHERE id = %s
                    """, (status, task_id))
                else:
                    cur.execute("""
                        UPDATE queue_tasks
                        SET status = %s,
                            completed_at = NOW(),
                            error_message = %s
                        WHERE id = %s
                    """, (status, error_message, task_id))
                
                conn.commit()
        
        logger.info(f"[QUEUE] Task {task_id} -> {status}")
    
    def worker_loop(self):
        """
        Main worker loop - processes tasks from the queue.
        
        This runs in a background thread and continuously:
        1. Locks next available task
        2. Executes it (calling Ollama DIRECTLY)
        3. Updates task status
        """
        logger.info("[WORKER] Worker loop started")
        
        while not self._shutdown:
            try:
                # Lock next task
                task = self._lock_next_task()
                if not task:
                    time.sleep(1)
                    continue
                
                logger.info(
                    f"[WORKER] Processing task {task.id} "
                    f"[{task.task_type}] (attempt {task.attempts})"
                )
                
                # Execute based on task type
                try:
                    if task.task_type == 'tags':
                        execute_tag_generation(**task.payload)
                    elif task.task_type == 'descriptions':
                        execute_description_generation(**task.payload)
                    elif task.task_type == 'questions':
                        execute_question_generation(**task.payload)
                    else:
                        raise ValueError(f"Unknown task type: {task.task_type}")
                    
                    # Mark as ready
                    self._update_task_status(task.id, 'ready')
                
                except Exception as e:
                    logger.error(f"[WORKER] Task {task.id} failed: {e}", exc_info=True)
                    self._update_task_status(task.id, 'error', str(e))
            
            except Exception as e:
                logger.error(f"[WORKER] Worker loop error: {e}", exc_info=True)
                time.sleep(5)
        
        logger.info("[WORKER] Worker loop stopped")
    
    def watchdog_loop(self):
        """
        Watchdog loop - checks for timed-out tasks.
        
        Runs every 60 seconds and marks timed-out tasks as errors.
        """
        logger.info("[WATCHDOG] Watchdog loop started")
        
        while not self._shutdown:
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Find timed-out tasks
                        cur.execute("""
                            UPDATE queue_tasks
                            SET status = 'error',
                                error_message = 'Task timed out after 15 minutes',
                                completed_at = NOW()
                            WHERE status = 'processing'
                              AND timeout_at < NOW()
                            RETURNING id, task_type
                        """)
                        
                        timed_out = cur.fetchall()
                        conn.commit()
                        
                        for task_id, task_type in timed_out:
                            logger.warning(
                                f"[WATCHDOG] Task {task_id} [{task_type}] timed out"
                            )
                
                time.sleep(60)
            
            except Exception as e:
                logger.error(f"[WATCHDOG] Watchdog error: {e}", exc_info=True)
                time.sleep(60)
        
        logger.info("[WATCHDOG] Watchdog loop stopped")
    
    def start_worker(self):
        """Start worker thread."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(
                target=self.worker_loop,
                name="QueueWorker",
                daemon=True
            )
            self._worker_thread.start()
            logger.info("[QUEUE] Worker thread started")
    
    def start_watchdog(self):
        """Start watchdog thread."""
        if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
            self._watchdog_thread = threading.Thread(
                target=self.watchdog_loop,
                name="QueueWatchdog",
                daemon=True
            )
            self._watchdog_thread.start()
            logger.info("[QUEUE] Watchdog thread started")
    
    def start(self):
        """Start both worker and watchdog threads."""
        self.start_worker()
        self.start_watchdog()
    
    def shutdown(self):
        """Shutdown queue manager."""
        logger.info("[QUEUE] Shutting down...")
        self._shutdown = True
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get queue status.
        
        Returns:
            Dictionary with task counts by status
        """
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT status, COUNT(*) as count
                    FROM queue_tasks
                    GROUP BY status
                """)
                
                status_counts = {row['status']: row['count'] for row in cur.fetchall()}
                
                # Get total count
                cur.execute("SELECT COUNT(*) as total FROM queue_tasks")
                total = cur.fetchone()['total']
                
                return {
                    'total': total,
                    'queued': status_counts.get('queued', 0),
                    'processing': status_counts.get('processing', 0),
                    'ready': status_counts.get('ready', 0),
                    'error': status_counts.get('error', 0)
                }
    
    def clear_completed_tasks(self) -> int:
        """
        Clear completed and errored tasks.
        
        Returns:
            Number of tasks deleted
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM queue_tasks
                    WHERE status IN ('ready', 'error')
                """)
                deleted_count = cur.rowcount
                conn.commit()
        
        logger.info(f"[QUEUE] Cleared {deleted_count} completed tasks")
        return deleted_count


# Singleton instance
_queue_manager_v2 = None


def get_queue_manager_v2() -> QueueManagerV2:
    """Get singleton queue manager instance."""
    global _queue_manager_v2
    if _queue_manager_v2 is None:
        _queue_manager_v2 = QueueManagerV2()
    return _queue_manager_v2
