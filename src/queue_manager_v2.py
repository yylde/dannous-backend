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
    execute_question_generation,
    execute_safety_check
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
        self.database_url = database_url or settings.database_url
        self._shutdown = False
        self._worker_threads = []
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
                result = cur.fetchone()
                if not result:
                    raise Exception("Failed to insert task into queue")
                task_id = result[0]
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
    
    def enqueue_tasks_batch(
        self,
        task_type: str,
        priority: int,
        book_id: str,
        chapter_id: Optional[str],
        payloads: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Enqueue multiple tasks atomically (e.g., one per grade level).
        
        Deletes conflicting tasks and inserts all new tasks in ONE transaction.
        This prevents race conditions between concurrent batch enqueues.
        
        Args:
            task_type: Type of task ('questions', etc.)
            priority: Priority level
            book_id: Draft book ID
            chapter_id: Chapter ID
            payloads: List of task payloads (each with different grade_level)
        
        Returns:
            List of task IDs
        """
        timeout_minutes = 15
        timeout_at = datetime.now() + timedelta(minutes=timeout_minutes)
        task_ids = []
        
        # Perform DELETE and INSERT in ONE transaction to prevent race conditions
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: Delete conflicting tasks
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
                if deleted_count > 0:
                    logger.info(f"[QUEUE] Deleted {deleted_count} conflicting {task_type} tasks")
                
                # Step 2: Insert all new tasks
                # Use ON CONFLICT DO NOTHING to handle concurrent inserts gracefully
                # (relies on unique constraint from migration 013)
                for payload in payloads:
                    cur.execute("""
                        INSERT INTO queue_tasks (
                            task_type, priority, status, book_id, chapter_id, 
                            payload, timeout_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
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
                    result = cur.fetchone()
                    if result:  # Only add to task_ids if insert succeeded (not conflicted)
                        task_id = result[0]
                        task_ids.append(str(task_id))
                
                # Commit both DELETE and INSERT together
                conn.commit()
        
        logger.info(f"[QUEUE] Batch enqueued {len(task_ids)} {task_type} tasks for chapter {chapter_id}")
        return task_ids
    
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
    
    def get_status(self) -> Dict[str, Any]:
        """Get queue status for monitoring."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Count tasks by status
                cur.execute("""
                    SELECT status, COUNT(*) as count
                    FROM queue_tasks
                    GROUP BY status
                """)
                status_counts = {row['status']: row['count'] for row in cur.fetchall()}
                
                # Get all active tasks (queued + processing only) with book titles
                cur.execute("""
                    SELECT q.id, q.task_type, q.priority, q.status, q.book_id, q.chapter_id,
                           q.payload, q.attempts, q.created_at, q.locked_at, q.timeout_at,
                           b.title as book_title
                    FROM queue_tasks q
                    LEFT JOIN books b ON q.book_id = b.id
                    WHERE q.status IN ('queued', 'processing')
                    ORDER BY q.priority ASC, q.created_at ASC
                    LIMIT 100
                """)
                active_tasks = []
                for row in cur.fetchall():
                    active_tasks.append({
                        'id': str(row['id']),
                        'task_type': row['task_type'],
                        'priority': row['priority'],
                        'status': row['status'],
                        'book_id': row['book_id'],
                        'chapter_id': row['chapter_id'],
                        'payload': row['payload'],
                        'attempts': row['attempts'],
                        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                        'locked_at': row['locked_at'].isoformat() if row['locked_at'] else None,
                        'timeout_at': row['timeout_at'].isoformat() if row['timeout_at'] else None,
                        'book_title': row['book_title']
                    })
                
                # Get ready tasks (completed successfully) with book titles
                cur.execute("""
                    SELECT q.id, q.task_type, q.priority, q.status, q.book_id, q.chapter_id,
                           q.payload, q.attempts, q.created_at, q.locked_at, q.completed_at,
                           b.title as book_title
                    FROM queue_tasks q
                    LEFT JOIN books b ON q.book_id = b.id
                    WHERE q.status = 'ready'
                    ORDER BY q.priority ASC, q.completed_at DESC
                    LIMIT 100
                """)
                ready_tasks = []
                for row in cur.fetchall():
                    ready_tasks.append({
                        'id': str(row['id']),
                        'task_type': row['task_type'],
                        'priority': row['priority'],
                        'status': row['status'],
                        'book_id': row['book_id'],
                        'chapter_id': row['chapter_id'],
                        'payload': row['payload'],
                        'attempts': row['attempts'],
                        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                        'locked_at': row['locked_at'].isoformat() if row['locked_at'] else None,
                        'completed_at': row['completed_at'].isoformat() if row['completed_at'] else None,
                        'book_title': row['book_title']
                    })
                
                # Get error tasks (completed with errors) with book titles
                cur.execute("""
                    SELECT q.id, q.task_type, q.priority, q.status, q.book_id, q.chapter_id,
                           q.payload, q.attempts, q.created_at, q.locked_at, q.completed_at,
                           q.error_message, b.title as book_title
                    FROM queue_tasks q
                    LEFT JOIN books b ON q.book_id = b.id
                    WHERE q.status = 'error'
                    ORDER BY q.priority ASC, q.completed_at DESC
                    LIMIT 100
                """)
                error_tasks = []
                for row in cur.fetchall():
                    error_tasks.append({
                        'id': str(row['id']),
                        'task_type': row['task_type'],
                        'priority': row['priority'],
                        'status': row['status'],
                        'book_id': row['book_id'],
                        'chapter_id': row['chapter_id'],
                        'payload': row['payload'],
                        'attempts': row['attempts'],
                        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                        'locked_at': row['locked_at'].isoformat() if row['locked_at'] else None,
                        'completed_at': row['completed_at'].isoformat() if row['completed_at'] else None,
                        'error_message': row['error_message'],
                        'book_title': row['book_title']
                    })
                
                return {
                    'total_queued': status_counts.get('queued', 0),
                    'total_processing': status_counts.get('processing', 0),
                    'total_ready': status_counts.get('ready', 0),
                    'total_error': status_counts.get('error', 0),
                    'active_tasks': active_tasks,
                    'ready_tasks': ready_tasks,
                    'error_tasks': error_tasks
                }
    
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
                        # Check if this is actually a safety check disguised as tags
                        if task.payload.get('is_safety_check') or 'book_text' in task.payload:
                            execute_safety_check(**task.payload)
                        else:
                            execute_tag_generation(**task.payload)
                    elif task.task_type == 'descriptions':
                        execute_description_generation(**task.payload)
                    elif task.task_type == 'questions':
                        execute_question_generation(**task.payload)
                    elif task.task_type == 'safety_check':
                        execute_safety_check(**task.payload)
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
        """Start worker threads."""
        # Clear any dead threads
        self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
        
        # Start missing threads
        current_count = len(self._worker_threads)
        target_count = settings.queue_worker_count
        
        if current_count < target_count:
            for i in range(current_count, target_count):
                t = threading.Thread(
                    target=self.worker_loop,
                    name=f"QueueWorker-{i+1}",
                    daemon=True
                )
                t.start()
                self._worker_threads.append(t)
            
            logger.info(f"[QUEUE] Started {target_count - current_count} worker threads (total: {target_count})")
    
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
    
    def clear_all_tasks(self) -> int:
        """
        Clear ALL tasks from the queue regardless of status.
        This includes queued, processing, ready, and error tasks.
        
        Returns:
            Number of tasks deleted
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM queue_tasks")
                deleted_count = cur.rowcount
                conn.commit()
        
        logger.info(f"[QUEUE] Cleared ALL {deleted_count} tasks from queue")
        return deleted_count
    
    def delete_task(self, task_id: str) -> bool:
        """
        Delete a specific task from the queue.
        
        Args:
            task_id: Task ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM queue_tasks
                    WHERE id = %s
                """, (task_id,))
                deleted_count = cur.rowcount
                conn.commit()
        
        if deleted_count > 0:
            logger.info(f"[QUEUE] Deleted task {task_id}")
            return True
        return False
    
    def get_task_for_book(self, book_id: str, task_type: str) -> Optional[Dict[str, Any]]:
        """
        Get most recent task for book-level operations.
        
        Used for status calculation - finds queued, processing, or error tasks.
        
        Args:
            book_id: Draft book ID
            task_type: Type of task ('tags', 'descriptions')
        
        Returns:
            Task dict with 'status' field, or None if no active task
        """
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, status, created_at, payload
                    FROM queue_tasks
                    WHERE book_id = %s
                      AND task_type = %s
                      AND chapter_id IS NULL
                      AND status IN ('queued', 'processing', 'error')
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (book_id, task_type))
                
                row = cur.fetchone()
                if row:
                    return dict(row)
                return None
    
    def get_tasks_for_chapter(self, chapter_id: str, task_type: str) -> List[Dict[str, Any]]:
        """
        Get all active tasks for a chapter.
        
        Used for status calculation - finds queued, processing, or error tasks.
        
        Args:
            chapter_id: Chapter ID
            task_type: Type of task ('questions')
        
        Returns:
            List of task dicts with 'status' field
        """
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, status, created_at
                    FROM queue_tasks
                    WHERE chapter_id = %s
                      AND task_type = %s
                      AND status IN ('queued', 'processing', 'error')
                    ORDER BY created_at DESC
                """, (chapter_id, task_type))
                
                rows = cur.fetchall()
                return [dict(row) for row in rows]


# Singleton instance
_queue_manager_v2 = None


def get_queue_manager_v2() -> QueueManagerV2:
    """Get singleton queue manager instance."""
    global _queue_manager_v2
    if _queue_manager_v2 is None:
        _queue_manager_v2 = QueueManagerV2()
    return _queue_manager_v2
