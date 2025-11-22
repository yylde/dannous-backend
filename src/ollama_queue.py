"""Priority queue system for Ollama API calls.

This module implements a priority-based FIFO queue system for managing Ollama API calls.
Tasks are processed in priority order (1=highest, 3=lowest), with FIFO ordering within each priority level.

Priority Levels:
- Priority 1 (HIGHEST): Genre and tag generation
- Priority 2 (MEDIUM): Description and synopsis generation
- Priority 3 (LOWEST): Question generation and chapter title generation
"""

import logging
import queue
import threading
import time
import json
import psycopg2
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, List
from enum import IntEnum
from src.config import settings

logger = logging.getLogger(__name__)


class TaskPriority(IntEnum):
    """Priority levels for Ollama tasks (lower number = higher priority)."""
    GENRE_TAG = 1
    DESCRIPTION = 2
    QUESTION = 3


@dataclass(order=True)
class OllamaTask:
    """Represents a queued Ollama task with priority and FIFO ordering."""
    priority: int
    task_id: int
    func: Callable = field(compare=False)
    args: tuple = field(compare=False, default_factory=tuple)
    kwargs: dict = field(compare=False, default_factory=dict)
    result_queue: queue.Queue = field(compare=False, default=None)
    task_name: str = field(compare=False, default="")
    task_type: str = field(compare=False, default="unknown")  # description, tags, questions
    book_id: Optional[str] = field(compare=False, default=None)
    chapter_id: Optional[str] = field(compare=False, default=None)


class OllamaQueueManager:
    """
    Manages priority-based queuing for Ollama API calls.
    
    Uses a single priority queue with multiple worker threads to process tasks.
    Tasks are executed in priority order (FIFO within each priority level).
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern to ensure only one queue manager exists."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, num_workers: int = None, database_url: Optional[str] = None):
        """Initialize the queue manager.
        
        Args:
            num_workers: Number of worker threads (default: 1)
            database_url: Database connection URL for persistence (optional)
        """
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self._task_queue = queue.PriorityQueue()
        self._workers = []
        self._shutdown = False
        self._task_counter = 0
        self._counter_lock = threading.Lock()
        # Use configured worker count if not specified, defaulting to 1
        self._num_workers = max(1, num_workers or settings.queue_worker_count)
        self._pending_tasks = {}  # Track pending tasks by ID for detailed info
        self._pending_tasks_lock = threading.Lock()
        self._database_url = database_url
        self._db_task_map = {}  # Maps task_id to database UUID
        
        logger.info(f"Initializing OllamaQueueManager with {self._num_workers} worker(s)")
        self._start_workers()
    
    def _start_workers(self):
        """Start worker threads to process tasks."""
        for i in range(self._num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"OllamaWorker-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)
            logger.info(f"Started worker thread: {worker.name}")
    
    def _worker_loop(self):
        """Main loop for worker threads."""
        thread_name = threading.current_thread().name
        logger.info(f"{thread_name} started and ready to process tasks")
        
        while True:
            try:
                task = self._task_queue.get(timeout=1.0)
                
                if task.task_type == 'shutdown':
                    self._task_queue.task_done()
                    logger.info(f"{thread_name} received shutdown sentinel")
                    break
                
                self._execute_task(task)
                self._task_queue.task_done()
                
            except queue.Empty:
                if self._shutdown:
                    break
                continue
            except Exception as e:
                logger.error(f"{thread_name} encountered error: {e}", exc_info=True)
        
        logger.info(f"{thread_name} shutting down")
    
    def _execute_task(self, task: OllamaTask):
        """Execute a single task with retry logic."""
        thread_name = threading.current_thread().name
        priority_name = self._get_priority_name(task.priority)
        
        db_task_id = self._db_task_map.get(task.task_id)
        
        if db_task_id:
            self._update_task_status(db_task_id, 'processing')
        
        logger.info(
            f"{thread_name} executing task #{task.task_id} "
            f"[{priority_name}]: {task.task_name}"
        )
        
        start_time = time.time()
        max_retries = 3
        retry_delay = 1.0
        task_failed = False
        
        try:
            for attempt in range(max_retries):
                try:
                    result = task.func(*task.args, **task.kwargs)
                    
                    if task.result_queue is not None:
                        task.result_queue.put(('success', result))
                    
                    elapsed = time.time() - start_time
                    logger.info(
                        f"{thread_name} completed task #{task.task_id} "
                        f"[{priority_name}] in {elapsed:.2f}s"
                    )
                    
                    if db_task_id:
                        self._update_task_status(db_task_id, 'completed')
                    return
                    
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{thread_name} task #{task.task_id} attempt {attempt + 1} failed: {e}, "
                            f"retrying in {retry_delay}s..."
                        )
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.error(
                            f"{thread_name} failed task #{task.task_id} "
                            f"[{priority_name}] after {max_retries} attempts: {e}",
                            exc_info=True
                        )
                        
                        if task.result_queue is not None:
                            task.result_queue.put(('error', e))
                        
                        task_failed = True
        finally:
            db_task_id = self._db_task_map.pop(task.task_id, None)
            if db_task_id:
                if task_failed:
                    self._update_task_status(db_task_id, 'failed')
                self._delete_task_from_db(db_task_id)
    
    def _get_priority_name(self, priority: int) -> str:
        """Get human-readable name for priority level."""
        priority_names = {
            TaskPriority.GENRE_TAG: "GENRE/TAG",
            TaskPriority.DESCRIPTION: "DESCRIPTION",
            TaskPriority.QUESTION: "QUESTION"
        }
        return priority_names.get(priority, f"PRIORITY-{priority}")
    
    def _get_next_task_id(self) -> int:
        """Get next task ID (thread-safe counter)."""
        with self._counter_lock:
            self._task_counter += 1
            return self._task_counter
    
    def submit_task(
        self,
        func: Callable,
        priority: TaskPriority,
        *args,
        task_name: str = "",
        task_type: str = "unknown",
        book_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        timeout: Optional[float] = 300.0,
        **kwargs
    ) -> Any:
        """
        Submit a task to the queue and wait for result.
        
        Args:
            func: Function to execute
            priority: Task priority (TaskPriority enum)
            *args: Positional arguments for func
            task_name: Descriptive name for logging (keyword-only)
            task_type: Type of task (description, tags, questions)
            book_id: Book/draft ID associated with task
            chapter_id: Chapter ID if applicable
            timeout: Maximum time to wait for result in seconds (keyword-only, default: 300)
            **kwargs: Keyword arguments for func
        
        Returns:
            Result from the function execution
        
        Raises:
            TimeoutError: If the task doesn't complete within timeout
            Exception: If the task execution fails
        """
        if self._shutdown:
            raise RuntimeError("Queue manager is shut down")
        
        result_queue = queue.Queue()
        task_id = self._get_next_task_id()
        
        task = OllamaTask(
            priority=int(priority),
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            result_queue=result_queue,
            task_name=task_name or func.__name__,
            task_type=task_type,
            book_id=book_id,
            chapter_id=chapter_id
        )
        
        # Track pending task
        with self._pending_tasks_lock:
            self._pending_tasks[task_id] = {
                'task_id': task_id,
                'priority': task.priority,
                'task_name': task.task_name,
                'task_type': task_type,
                'book_id': book_id,
                'chapter_id': chapter_id
            }
        
        # Save task to database for persistence
        db_task_id = self._save_task_to_db(task)
        if db_task_id:
            self._db_task_map[task_id] = db_task_id
        
        priority_name = self._get_priority_name(task.priority)
        logger.info(f"Submitting task #{task_id} [{priority_name}]: {task.task_name}")
        
        self._task_queue.put(task)
        
        try:
            status, result = result_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(
                f"Task #{task_id} [{priority_name}] did not complete within {timeout}s"
            )
        finally:
            # Remove from pending tasks
            with self._pending_tasks_lock:
                self._pending_tasks.pop(task_id, None)
        
        if status == 'error':
            raise result
        
        return result
    
    def enqueue_task(
        self,
        func: Callable,
        priority: TaskPriority,
        *args,
        task_name: str = "",
        task_type: str = "unknown",
        book_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        **kwargs
    ) -> int:
        """
        Enqueue a task without waiting for result (non-blocking).
        
        Args:
            func: Function to execute
            priority: Task priority (TaskPriority enum)
            *args: Positional arguments for func
            task_name: Descriptive name for logging (keyword-only)
            task_type: Type of task (description, tags, questions)
            book_id: Book/draft ID associated with task
            chapter_id: Chapter ID if applicable
            **kwargs: Keyword arguments for func
        
        Returns:
            Task ID (integer)
        """
        if self._shutdown:
            raise RuntimeError("Queue manager is shut down")
        
        task_id = self._get_next_task_id()
        
        task = OllamaTask(
            priority=int(priority),
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            result_queue=None,  # No result queue for non-blocking
            task_name=task_name or func.__name__,
            task_type=task_type,
            book_id=book_id,
            chapter_id=chapter_id
        )
        
        # Track pending task
        with self._pending_tasks_lock:
            self._pending_tasks[task_id] = {
                'task_id': task_id,
                'priority': task.priority,
                'task_name': task.task_name,
                'task_type': task_type,
                'book_id': book_id,
                'chapter_id': chapter_id
            }
        
        # Save task to database for persistence
        db_task_id = self._save_task_to_db(task)
        if db_task_id:
            self._db_task_map[task_id] = db_task_id
        
        priority_name = self._get_priority_name(task.priority)
        logger.info(f"Enqueued task #{task_id} [{priority_name}]: {task.task_name} (non-blocking)")
        
        self._task_queue.put(task)
        
        return task_id
    
    def get_queue_size(self) -> int:
        """Get current number of tasks in queue."""
        return self._task_queue.qsize()
    
    def get_queue_info(self) -> Dict[str, Any]:
        """Get information about the current queue state.
        
        Returns:
            Dict with queue size, worker count, and detailed pending tasks
        """
        with self._pending_tasks_lock:
            in_memory_tasks = list(self._pending_tasks.values())
        
        db_tasks = []
        if self._database_url:
            conn = self._get_db_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, task_type, book_id, chapter_id, priority, status, created_at
                            FROM queue_tasks
                            WHERE status != 'completed'
                            ORDER BY priority, created_at
                        """)
                        
                        rows = cur.fetchall()
                        for row in rows:
                            db_tasks.append({
                                'task_id': str(row[0]),  # Use db_id as task_id for UI display
                                'db_id': str(row[0]),
                                'task_type': row[1],
                                'book_id': str(row[2]) if row[2] else None,
                                'chapter_id': str(row[3]) if row[3] else None,
                                'priority': row[4],
                                'status': row[5],
                                'created_at': row[6].isoformat() if row[6] else None
                            })
                except Exception as e:
                    logger.error(f"Failed to fetch tasks from database: {e}")
                finally:
                    conn.close()
        
        db_task_ids = {task['db_id'] for task in db_tasks}
        memory_task_db_ids = {str(self._db_task_map.get(task['task_id'])) for task in in_memory_tasks if self._db_task_map.get(task['task_id'])}
        
        combined_tasks = db_tasks.copy()
        for task in in_memory_tasks:
            task_db_id = self._db_task_map.get(task['task_id'])
            if not task_db_id or str(task_db_id) not in db_task_ids:
                combined_tasks.append(task)
        
        return {
            'queue_size': self._task_queue.qsize(),
            'worker_count': len(self._workers),
            'active_workers': sum(1 for w in self._workers if w.is_alive()),
            'shutdown': self._shutdown,
            'pending_tasks': combined_tasks
        }
    
    def delete_tasks_for_book_chapter(self, book_id: Optional[str] = None, chapter_id: Optional[str] = None, task_type: Optional[str] = None) -> int:
        """Delete specific pending tasks from queue by book_id and/or chapter_id and/or task_type.
        
        Args:
            book_id: Delete tasks for this book (UUID string)
            chapter_id: Delete tasks for this chapter (UUID string)
            task_type: Delete tasks of this type (e.g., 'tags', 'descriptions', 'questions')
            
        Returns:
            Number of tasks that were removed
        """
        if not book_id and not chapter_id and not task_type:
            return 0
        
        deleted_count = 0
        remaining_tasks = []
        
        # Drain queue and filter out matching tasks
        while not self._task_queue.empty():
            try:
                task = self._task_queue.get_nowait()
                if task.task_type == 'shutdown':  # Shutdown sentinel
                    remaining_tasks.append(task)
                    continue
                
                # Check if task matches deletion criteria
                should_delete = False
                if book_id and chapter_id:
                    should_delete = (task.book_id == book_id and task.chapter_id == chapter_id)
                elif book_id and task_type:
                    should_delete = (task.book_id == book_id and task.task_type == task_type)
                elif book_id:
                    should_delete = (task.book_id == book_id)
                elif chapter_id:
                    should_delete = (task.chapter_id == chapter_id)
                elif task_type:
                    should_delete = (task.task_type == task_type)
                
                if should_delete:
                    deleted_count += 1
                    # Delete from database if it has a DB ID
                    if hasattr(task, 'db_id') and task.db_id:
                        self._delete_task_from_db(task.db_id)
                    # Send error to any waiting threads
                    if task.result_queue is not None:
                        task.result_queue.put(('error', Exception('Task cancelled due to regeneration')))
                    self._task_queue.task_done()
                else:
                    remaining_tasks.append(task)
                    self._task_queue.task_done()
            except queue.Empty:
                break
        
        # Re-add remaining tasks to queue
        for task in remaining_tasks:
            self._task_queue.put(task)
        
        # Also delete from database
        if self._database_url:
            conn = self._get_db_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        conditions = []
                        params = []
                        
                        if book_id:
                            conditions.append("book_id = %s")
                            params.append(book_id)
                        if chapter_id:
                            conditions.append("chapter_id = %s")
                            params.append(chapter_id)
                        if task_type:
                            conditions.append("task_type = %s")
                            params.append(task_type)
                        
                        if conditions:
                            where_clause = " AND ".join(conditions)
                            cur.execute(f"DELETE FROM queue_tasks WHERE {where_clause}", tuple(params))
                        
                        conn.commit()
                except Exception as e:
                    logger.error(f"Failed to delete tasks from database: {e}")
                    conn.rollback()
                finally:
                    conn.close()
        
        logger.info(f"Deleted {deleted_count} tasks for book_id={book_id}, chapter_id={chapter_id}, task_type={task_type}")
        return deleted_count
    
    def flush_queue(self) -> int:
        """Clear all pending tasks from the queue.
        
        Returns:
            Number of tasks that were removed
        """
        flushed_count = 0
        
        # Drain the queue
        while not self._task_queue.empty():
            try:
                task = self._task_queue.get_nowait()
                if task.task_type != 'shutdown':  # Don't count shutdown sentinels
                    flushed_count += 1
                    # Send error to any waiting threads
                    if task.result_queue is not None:
                        task.result_queue.put(('error', Exception('Queue flushed')))
                    self._task_queue.task_done()
                else:
                    # Put shutdown sentinel back? Or just drop it if we are flushing?
                    # If we flush, we probably want to keep the queue empty but running?
                    # If we drop sentinel, workers might not stop if they were supposed to.
                    # But flush_queue usually implies clearing tasks, not stopping workers.
                    # Let's put it back if we encounter it, or just ignore it (it's not a task).
                    # For safety, let's put it back to ensure shutdown signal persists if it was there.
                    self._task_queue.task_done()
                    self._task_queue.put(task)
            except queue.Empty:
                break
        
        logger.info(f"Flushed {flushed_count} tasks from queue")
        return flushed_count
    
    def _get_db_connection(self):
        """Get database connection if database_url is configured."""
        if not self._database_url:
            return None
        try:
            return psycopg2.connect(self._database_url)
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return None
    
    def _save_task_to_db(self, task: OllamaTask) -> Optional[str]:
        """Save task to database for persistence.
        
        Args:
            task: The OllamaTask to save
            
        Returns:
            Database UUID of saved task, or None if save failed
        """
        if not self._database_url:
            return None
        
        conn = self._get_db_connection()
        if not conn:
            return None
        
        try:
            with conn.cursor() as cur:
                args_json = json.dumps({
                    'task_name': task.task_name,
                    'args': [str(arg) if not isinstance(arg, (str, int, float, bool, type(None))) else arg 
                             for arg in task.args],
                    'kwargs': {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v) 
                               for k, v in task.kwargs.items()}
                })
                
                cur.execute("""
                    INSERT INTO queue_tasks (task_type, book_id, chapter_id, priority, args, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    task.task_type,
                    task.book_id,
                    task.chapter_id,
                    task.priority,
                    args_json,
                    'pending'
                ))
                
                db_id = cur.fetchone()[0]
                conn.commit()
                logger.debug(f"Saved task #{task.task_id} to database with ID {db_id}")
                return str(db_id)
        except Exception as e:
            logger.error(f"Failed to save task to database: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()
    
    def _update_task_status(self, db_task_id: str, status: str):
        """Update task status in database.
        
        Args:
            db_task_id: Database UUID of the task
            status: New status (pending, processing, completed, failed)
        """
        if not self._database_url or not db_task_id:
            return
        
        conn = self._get_db_connection()
        if not conn:
            return
        
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue_tasks SET status = %s WHERE id = %s",
                    (status, db_task_id)
                )
                conn.commit()
                logger.debug(f"Updated task {db_task_id} status to '{status}'")
        except Exception as e:
            logger.error(f"Failed to update task status in database: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def _delete_task_from_db(self, db_task_id: str):
        """Delete completed task from database.
        
        Args:
            db_task_id: Database UUID of the task to delete
        """
        if not self._database_url or not db_task_id:
            return
        
        conn = self._get_db_connection()
        if not conn:
            return
        
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM queue_tasks WHERE id = %s", (db_task_id,))
                conn.commit()
                logger.debug(f"Deleted task {db_task_id} from database")
        except Exception as e:
            logger.error(f"Failed to delete task from database: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def load_persistent_tasks(self) -> List[Dict]:
        """Load pending tasks from database.
        
        This method retrieves tasks that were pending when the server last shut down.
        Note: Tasks cannot be automatically re-executed because function references 
        cannot be serialized. This method returns task metadata for inspection and 
        potential manual re-triggering.
        
        Returns:
            List of task dictionaries with metadata
        """
        if not self._database_url:
            logger.info("No database URL configured, skipping persistent task loading")
            return []
        
        conn = self._get_db_connection()
        if not conn:
            return []
        
        pending_tasks = []
        
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, task_type, book_id, chapter_id, priority, args, created_at
                    FROM queue_tasks
                    ORDER BY priority, created_at
                """)
                
                rows = cur.fetchall()
                
                for row in rows:
                    task_data = {
                        'db_id': str(row[0]),
                        'task_type': row[1],
                        'book_id': str(row[2]) if row[2] else None,
                        'chapter_id': str(row[3]) if row[3] else None,
                        'priority': row[4],
                        'args': row[5],
                        'created_at': row[6].isoformat() if row[6] else None
                    }
                    pending_tasks.append(task_data)
                
                if pending_tasks:
                    logger.warning(
                        f"Found {len(pending_tasks)} pending tasks in database from previous session. "
                        f"These tasks cannot be automatically re-executed and should be manually re-triggered "
                        f"by the application if still needed."
                    )
                    
                    cur.execute("DELETE FROM queue_tasks")
                    conn.commit()
                    logger.info(f"Cleared {len(pending_tasks)} stale tasks from database")
                else:
                    logger.info("No pending tasks found in database")
        
        except Exception as e:
            logger.error(f"Failed to load persistent tasks: {e}")
            conn.rollback()
        finally:
            conn.close()
        
        return pending_tasks
    
    def shutdown(self, wait: bool = True, timeout: float = 30.0):
        """
        Shutdown the queue manager gracefully.
        
        Args:
            wait: If True, wait for all tasks to complete
            timeout: Maximum time to wait for shutdown (seconds)
        """
        if self._shutdown:
            logger.warning("Queue manager already shut down")
            return
        
        logger.info("Shutting down OllamaQueueManager...")
        
        if wait:
            pending_count = self._task_queue.qsize()
            if pending_count > 0:
                logger.info(f"Waiting for {pending_count} pending tasks to complete...")
                try:
                    self._task_queue.join()
                    logger.info("All tasks completed")
                except Exception as e:
                    logger.error(f"Error during queue join: {e}")
        
        self._shutdown = True
        
        self._shutdown = True
        
        for _ in self._workers:
            # Use a sentinel task with high priority (0) to ensure it's picked up
            sentinel = OllamaTask(
                priority=0, 
                task_id=0, 
                func=lambda: None, 
                task_type='shutdown', 
                task_name='SHUTDOWN'
            )
            self._task_queue.put(sentinel)
        
        start_time = time.time()
        for worker in self._workers:
            remaining = timeout - (time.time() - start_time)
            if remaining > 0:
                worker.join(timeout=remaining)
                if worker.is_alive():
                    logger.warning(f"Worker {worker.name} did not shut down in time")
            else:
                logger.warning(f"Timeout reached, worker {worker.name} may still be running")
        
        logger.info("OllamaQueueManager shutdown complete")


_queue_manager_instance: Optional[OllamaQueueManager] = None


def get_queue_manager() -> OllamaQueueManager:
    """Get or create the global queue manager instance."""
    global _queue_manager_instance
    if _queue_manager_instance is None:
        _queue_manager_instance = OllamaQueueManager()
    return _queue_manager_instance


def shutdown_queue_manager(wait: bool = True, timeout: float = 30.0):
    """Shutdown the global queue manager."""
    global _queue_manager_instance
    if _queue_manager_instance is not None:
        _queue_manager_instance.shutdown(wait=wait, timeout=timeout)
        _queue_manager_instance = None


def queue_ollama_call(
    func: Callable,
    priority: TaskPriority,
    task_name: str,
    prompt: str,
    force_json_format: bool = False,
    task_type: str = "unknown",
    book_id: Optional[str] = None,
    chapter_id: Optional[str] = None
) -> Any:
    """
    Helper function to submit an Ollama API call to the queue.
    
    Args:
        func: The Ollama function to call
        priority: Task priority level
        task_name: Descriptive name for the task
        prompt: The prompt string to pass to Ollama
        force_json_format: Whether to force JSON format
        task_type: Type of task (description, tags, questions)
        book_id: Book/draft ID if applicable
        chapter_id: Chapter ID if applicable
    
    Returns:
        Result from the Ollama function
    """
    manager = get_queue_manager()
    return manager.submit_task(
        func, 
        priority, 
        prompt, 
        force_json_format, 
        task_name=task_name,
        task_type=task_type,
        book_id=book_id,
        chapter_id=chapter_id
    )
