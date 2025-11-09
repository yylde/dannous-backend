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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from enum import IntEnum

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
    
    def __init__(self, num_workers: int = 1):
        """Initialize the queue manager.
        
        Args:
            num_workers: Number of worker threads (default: 1)
        """
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self._task_queue = queue.PriorityQueue()
        self._workers = []
        self._shutdown = False
        self._task_counter = 0
        self._counter_lock = threading.Lock()
        self._num_workers = max(1, num_workers)
        self._pending_tasks = {}  # Track pending tasks by ID for detailed info
        self._pending_tasks_lock = threading.Lock()
        
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
                
                if task is None:
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
        
        logger.info(
            f"{thread_name} executing task #{task.task_id} "
            f"[{priority_name}]: {task.task_name}"
        )
        
        start_time = time.time()
        max_retries = 3
        retry_delay = 1.0
        
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
    
    def get_queue_size(self) -> int:
        """Get current number of tasks in queue."""
        return self._task_queue.qsize()
    
    def get_queue_info(self) -> Dict[str, Any]:
        """Get information about the current queue state.
        
        Returns:
            Dict with queue size, worker count, and detailed pending tasks
        """
        with self._pending_tasks_lock:
            pending_tasks = list(self._pending_tasks.values())
        
        return {
            'queue_size': self._task_queue.qsize(),
            'worker_count': len(self._workers),
            'active_workers': sum(1 for w in self._workers if w.is_alive()),
            'shutdown': self._shutdown,
            'pending_tasks': pending_tasks
        }
    
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
                if task is not None:  # Don't count shutdown sentinels
                    flushed_count += 1
                    # Send error to any waiting threads
                    if task.result_queue is not None:
                        task.result_queue.put(('error', Exception('Queue flushed')))
                    self._task_queue.task_done()
            except queue.Empty:
                break
        
        logger.info(f"Flushed {flushed_count} tasks from queue")
        return flushed_count
    
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
        
        for _ in self._workers:
            self._task_queue.put(None)
        
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
