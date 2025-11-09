"""Dynamic status calculation for drafts and chapters.

This module calculates status dynamically based on:
1. Whether data exists (tags, description, questions)
2. Queue state (queued, processing, error tasks)
"""

import logging
from typing import Optional
from src.database import DatabaseManager
from src.queue_manager_v2 import get_queue_manager_v2

logger = logging.getLogger(__name__)


def get_tag_status(draft_id: str) -> str:
    """
    Calculate tag status dynamically.
    
    Priority order:
    1. Check queue first (queued/processing/error tasks take priority)
    2. Check if data exists (return 'ready')
    3. Otherwise return 'pending'
    
    Args:
        draft_id: Draft book ID
    
    Returns:
        Status string: 'ready', 'queued', 'processing', 'error', or 'pending'
    """
    db = DatabaseManager()
    draft = db.get_draft(draft_id)
    
    if not draft:
        return 'pending'
    
    # Check queue FIRST - active tasks take priority over existing data
    queue_mgr = get_queue_manager_v2()
    task = queue_mgr.get_task_for_book(draft_id, 'tags')
    if task:
        return task['status']  # 'queued', 'processing', 'error'
    
    # If no active task, check if tags exist
    tags = draft.get('tags', [])
    if tags and len(tags) > 0:
        return 'ready'
    
    return 'pending'


def get_description_status(draft_id: str) -> str:
    """
    Calculate description status dynamically.
    
    Priority order:
    1. Check queue first (queued/processing/error tasks take priority)
    2. Check if data exists (return 'ready')
    3. Otherwise return 'pending'
    
    Args:
        draft_id: Draft book ID
    
    Returns:
        Status string: 'ready', 'queued', 'processing', 'error', or 'pending'
    """
    db = DatabaseManager()
    draft = db.get_draft(draft_id)
    
    if not draft:
        return 'pending'
    
    # Check queue FIRST - active tasks take priority over existing data
    queue_mgr = get_queue_manager_v2()
    task = queue_mgr.get_task_for_book(draft_id, 'descriptions')
    if task:
        return task['status']  # 'queued', 'processing', 'error'
    
    # If no active task, check if description exists (handle NULL values)
    description = draft.get('description') or ''
    description = description.strip() if isinstance(description, str) else ''
    if description:
        return 'ready'
    
    return 'pending'


def get_question_status(chapter_id: str) -> str:
    """
    Calculate question status for a chapter.
    
    Priority order:
    1. Check queue first (queued/processing/error tasks take priority)
    2. Check if all questions exist (num_grades × 3)
    3. Otherwise return 'pending'
    
    Question status is 'ready' when:
    - The chapter has the expected number of questions (num_grades × 3)
    
    Args:
        chapter_id: Chapter ID
    
    Returns:
        Status string: 'ready', 'queued', 'processing', 'error', or 'pending'
    """
    db = DatabaseManager()
    
    # Get chapter's draft to find grades
    chapter = db.get_draft_chapter(chapter_id)
    if not chapter:
        return 'pending'
    
    draft_id = chapter.get('draft_id')
    if not draft_id:
        return 'pending'
    
    draft = db.get_draft(draft_id)
    if not draft:
        return 'pending'
    
    # Get grade levels from tags
    tags = draft.get('tags', [])
    grades = [tag for tag in tags if tag.startswith('grade-')]
    num_grades = len(grades)
    
    if num_grades == 0:
        return 'pending'  # No grades set yet
    
    # Check queue FIRST - active tasks take priority over existing data
    queue_mgr = get_queue_manager_v2()
    tasks = queue_mgr.get_tasks_for_chapter(chapter_id, 'questions')
    if tasks:
        # Prioritize statuses: processing > queued > error
        statuses = [t['status'] for t in tasks]
        if 'processing' in statuses:
            return 'processing'
        if 'queued' in statuses:
            return 'queued'
        if 'error' in statuses:
            return 'error'
    
    # If no active task, check if all questions exist
    # Query database directly instead of relying on cached chapter data
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) 
                FROM draft_questions 
                WHERE chapter_id = %s
            """, (chapter_id,))
            actual_count = cur.fetchone()[0]
    
    expected_count = num_grades * 3  # 3 questions per grade
    
    if actual_count >= expected_count:
        return 'ready'
    
    return 'pending'
