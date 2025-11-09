"""Background tasks for question generation."""

import logging
import threading
import time
import os
from src.question_generator import QuestionGenerator
from src.database import DatabaseManager, inject_vocabulary_abbr
from src.config import settings

logger = logging.getLogger(__name__)

# Control parallel vs sequential question generation
PARALLEL_GENERATION = os.environ.get('PARALLEL_GENERATION', 'true').lower() == 'true'


def generate_questions_worker(draft_id, chapter_id, chapter_number, title, content, html_content, grade_level, book_title, book_author, age_range, reading_level):
    """
    Worker function for generating questions for a single chapter/grade.
    This function runs in the Ollama queue worker thread and handles persistence.
    """
    db = DatabaseManager()
    
    try:
        logger.info(f"Worker generating questions for chapter {chapter_id}, grade {grade_level}")
        
        # At START: update grade status to 'generating'
        db.update_grade_status(chapter_id, grade_level, 'generating')
        db.compute_chapter_status(chapter_id)
        
        generator = QuestionGenerator()
        
        # Generate questions and vocabulary for this grade level
        questions_data, vocabulary_data = generator.generate_questions(
            title=book_title,
            author=book_author,
            chapter_number=chapter_number,
            chapter_title=title,
            chapter_text=content,
            reading_level=reading_level,
            age_range=age_range,
            grade_level=grade_level,
            num_questions=settings.questions_per_chapter,
            vocab_count=8,
            book_id=str(draft_id),
            chapter_id=str(chapter_id)
        )
        
        # Add grade_level to vocabulary items
        for vocab_item in vocabulary_data:
            vocab_item['grade_level'] = grade_level
        
        # Save questions for this grade level
        db.save_draft_questions(chapter_id, draft_id, questions_data, vocabulary_data, grade_level=grade_level)
        
        # After saving questions: update grade status to 'ready'
        db.update_grade_status(chapter_id, grade_level, 'ready')
        db.compute_chapter_status(chapter_id)
        
        logger.info(f"✓ Worker saved {len(questions_data)} questions for chapter {chapter_id}, {grade_level} - STATUS: READY")
        
        return {'success': True, 'questions': len(questions_data), 'vocabulary': len(vocabulary_data)}
        
    except Exception as e:
        logger.exception(f"✗ Worker failed to generate questions for chapter {chapter_id}, {grade_level}: {e}")
        
        # On ERROR: update grade status to 'error'
        db.update_grade_status(chapter_id, grade_level, 'error')
        db.compute_chapter_status(chapter_id)
        
        raise


def generate_questions_async(chapter_id, draft_id, title, content, html_content, age_range, reading_level):
    """Generate questions asynchronously in background for all detected grade levels."""
    try:
        db = DatabaseManager()
        db.update_chapter_question_status(chapter_id, 'generating')
        
        # Get book tags to determine grade levels
        draft = db.get_draft(draft_id)
        tags = draft.get('tags', [])
        
        # Extract grade-level tags from book tags
        grade_levels = [tag for tag in tags if tag.startswith('grade-')]
        
        # If no grade tags found, use reading level as fallback
        if not grade_levels:
            grade_levels = [reading_level or settings.default_reading_level]
            logger.warning(f"No grade tags found for draft {draft_id}, using reading level: {grade_levels[0]}")
        else:
            logger.info(f"Generating questions for {len(grade_levels)} grade levels: {grade_levels}")
        
        generator = QuestionGenerator()
        all_vocabulary = []
        
        # Generate questions and vocabulary for each grade level
        for grade_level in grade_levels:
            logger.info(f"Generating for {grade_level}...")
            
            questions_data, vocabulary_data = generator.generate_questions(
                title=draft.get('title', 'Book Draft'),
                author=draft.get('author', 'Unknown'),
                chapter_number=1,
                chapter_title=title,
                chapter_text=content,
                reading_level=reading_level or settings.default_reading_level,
                age_range=age_range or settings.default_age_range,
                grade_level=grade_level,
                num_questions=settings.questions_per_chapter,
                vocab_count=8,  # 8 words per grade level
                book_id=str(draft_id),
                chapter_id=str(chapter_id)
            )
            
            # Add grade_level to each vocabulary item (as requested by user)
            for vocab_item in vocabulary_data:
                vocab_item['grade_level'] = grade_level
            
            all_vocabulary.extend(vocabulary_data)
            
            # Save questions for this grade level
            db.save_draft_questions(chapter_id, draft_id, questions_data, vocabulary_data, grade_level=grade_level)
            
            logger.info(f"✓ Saved {len(questions_data)} questions and {len(vocabulary_data)} vocabulary for {grade_level}")
        
        # Apply vocabulary abbr tags to HTML content (combine all vocabulary)
        html_with_abbr = inject_vocabulary_abbr(html_content or content, all_vocabulary)
        
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_chapters 
                    SET html_formatting = %s
                    WHERE id = %s
                """, (html_with_abbr, chapter_id))
        
        # Mark chapter as ready - ALL grades have been processed
        db.update_chapter_question_status(chapter_id, 'ready')
        
        logger.info(f"✓ Generated questions for {len(grade_levels)} grade levels with {len(all_vocabulary)} total vocabulary items - STATUS: READY")
        
    except Exception as e:
        logger.exception(f"Failed to generate questions for chapter {chapter_id}")
        db = DatabaseManager()
        db.update_chapter_question_status(chapter_id, 'error')


def regenerate_questions_for_draft_async(draft_id):
    """Regenerate questions for all chapters in a draft based on current grade tags."""
    try:
        from src.ollama_queue import get_queue_manager
        
        db = DatabaseManager()
        
        # Get the draft with current tags
        draft = db.get_draft(draft_id)
        if not draft:
            logger.error(f"Draft {draft_id} not found")
            return
        
        # FIRST: Delete any existing pending question generation tasks for this book from the queue
        queue_manager = get_queue_manager()
        deleted_count = queue_manager.delete_tasks_for_book_chapter(book_id=draft_id)
        logger.info(f"Deleted {deleted_count} pending queue tasks for draft {draft_id}")
        
        tags = draft.get('tags', [])
        new_grade_levels = [tag for tag in tags if tag.startswith('grade-')]
        
        # Get existing grade levels that have questions
        existing_grade_levels = db.get_existing_grade_levels_for_draft(draft_id)
        
        # Determine which grades to delete and which to add
        grades_to_delete = [g for g in existing_grade_levels if g not in new_grade_levels]
        grades_to_add = [g for g in new_grade_levels if g not in existing_grade_levels]
        
        logger.info(f"Regenerating questions for draft {draft_id}")
        logger.info(f"  Current grades: {existing_grade_levels}")
        logger.info(f"  New grades: {new_grade_levels}")
        logger.info(f"  Grades to delete: {grades_to_delete}")
        logger.info(f"  Grades to add: {grades_to_add}")
        
        # Delete questions for removed grades from database
        if grades_to_delete:
            logger.info(f"Deleting questions for removed grades: {grades_to_delete}")
            db.delete_questions_by_grade_level(draft_id, grades_to_delete)
        
        # If no new grade tags, we're done after deletion
        if not new_grade_levels:
            logger.warning(f"No grade tags found for draft {draft_id} - deleted all grade-specific questions")
            return
        
        # Get all chapters for this draft
        chapters = db.get_draft_chapters(draft_id)
        
        if not chapters:
            logger.warning(f"No chapters found for draft {draft_id}")
            return
        
        # Determine which grades to regenerate
        # If there are new grades to add, only add those
        # Otherwise, regenerate ALL existing grades (force regeneration)
        grades_to_regenerate = grades_to_add if grades_to_add else new_grade_levels
        
        if grades_to_regenerate:
            # If regenerating all existing grades, delete existing questions first
            if not grades_to_add and new_grade_levels:
                logger.info(f"Force regenerating questions for all existing grades: {new_grade_levels}")
                for chapter in chapters:
                    with db.get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM draft_questions WHERE chapter_id = %s", (chapter['id'],))
                            cur.execute("DELETE FROM draft_vocabulary WHERE chapter_id = %s", (chapter['id'],))
            
            logger.info(f"Enqueuing question generation for {len(chapters)} chapters x {len(grades_to_regenerate)} grades = {len(chapters) * len(grades_to_regenerate)} tasks")
            
            # Create grade status records (status='pending') for each chapter/grade combination
            for chapter in chapters:
                for grade_level in grades_to_regenerate:
                    db.create_or_reset_grade_status(chapter['id'], grade_level, status='pending')
            
            # Enqueue non-blocking tasks for each chapter/grade combination
            from src.ollama_queue import TaskPriority
            task_count = 0
            
            for chapter in chapters:
                for grade_level in grades_to_regenerate:
                    # Enqueue non-blocking task
                    # Pass worker parameters as positional args to avoid conflicts with metadata params
                    task_id = queue_manager.enqueue_task(
                        generate_questions_worker,
                        TaskPriority.QUESTION,
                        # Worker function positional arguments (in correct order)
                        draft_id,
                        chapter['id'],  # chapter_id
                        chapter['chapter_number'],  # chapter_number
                        chapter['title'],  # title
                        chapter['content'],  # content
                        chapter.get('html_formatting'),  # html_content
                        grade_level,
                        draft.get('title', 'Book Draft'),  # book_title
                        draft.get('author', 'Unknown'),  # book_author
                        draft.get('age_range') or settings.default_age_range,  # age_range
                        draft.get('reading_level') or settings.default_reading_level,  # reading_level
                        # Queue metadata (keyword-only params)
                        task_name=f"Questions: Ch{chapter['chapter_number']} {grade_level}",
                        task_type="questions",
                        book_id=draft_id,
                        chapter_id=chapter['id']
                    )
                    
                    # Update grade status to 'queued' with queue_task_id
                    db.update_grade_status(chapter['id'], grade_level, 'queued', queue_task_id=task_id)
                    
                    task_count += 1
                
                # Compute and update chapter status from grade statuses
                db.compute_chapter_status(chapter['id'])
            
            logger.info(f"✓ Enqueued {task_count} question generation tasks for draft {draft_id} - tasks will process asynchronously")
        
    except Exception as e:
        logger.exception(f"✗ Failed to regenerate questions for draft {draft_id}: {e}")


def regenerate_single_chapter_questions_async(chapter_id, draft_id, title, content, html_content, age_range, reading_level):
    """Regenerate questions for a single chapter based on current draft grade tags."""
    try:
        db = DatabaseManager()
        db.update_chapter_question_status(chapter_id, 'generating')
        
        # Get book tags to determine grade levels
        draft = db.get_draft(draft_id)
        tags = draft.get('tags', [])
        
        # Extract grade-level tags from book tags
        grade_levels = [tag for tag in tags if tag.startswith('grade-')]
        
        # If no grade tags found, use reading level as fallback
        if not grade_levels:
            grade_levels = [reading_level or settings.default_reading_level]
            logger.warning(f"No grade tags found for draft {draft_id}, using reading level: {grade_levels[0]}")
        else:
            logger.info(f"Regenerating questions for chapter {chapter_id} with {len(grade_levels)} grade levels: {grade_levels}")
        
        # Delete all existing questions for this chapter (all grades)
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM draft_questions WHERE chapter_id = %s", (chapter_id,))
                cur.execute("DELETE FROM draft_vocabulary WHERE chapter_id = %s", (chapter_id,))
        
        logger.info(f"Deleted existing questions for chapter {chapter_id}")
        
        generator = QuestionGenerator()
        all_vocabulary = []
        
        # Generate questions and vocabulary for each grade level
        for grade_level in grade_levels:
            logger.info(f"Generating for {grade_level}...")
            
            questions_data, vocabulary_data = generator.generate_questions(
                title=draft.get('title', 'Book Draft'),
                author=draft.get('author', 'Unknown'),
                chapter_number=1,
                chapter_title=title,
                chapter_text=content,
                reading_level=reading_level or settings.default_reading_level,
                age_range=age_range or settings.default_age_range,
                grade_level=grade_level,
                num_questions=settings.questions_per_chapter,
                vocab_count=8,
                book_id=str(draft_id),
                chapter_id=str(chapter_id)
            )
            
            # Add grade_level to each vocabulary item
            for vocab_item in vocabulary_data:
                vocab_item['grade_level'] = grade_level
            
            all_vocabulary.extend(vocabulary_data)
            
            # Save questions for this grade level
            db.save_draft_questions(chapter_id, draft_id, questions_data, vocabulary_data, grade_level=grade_level)
            
            logger.info(f"✓ Saved {len(questions_data)} questions and {len(vocabulary_data)} vocabulary for {grade_level}")
        
        # Apply vocabulary abbr tags to HTML content (combine all vocabulary)
        html_with_abbr = inject_vocabulary_abbr(html_content or content, all_vocabulary)
        
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_chapters 
                    SET html_formatting = %s
                    WHERE id = %s
                """, (html_with_abbr, chapter_id))
        
        # Mark chapter as ready
        db.update_chapter_question_status(chapter_id, 'ready')
        
        logger.info(f"✓ Regenerated questions for chapter {chapter_id} with {len(grade_levels)} grade levels - STATUS: READY")
        
    except Exception as e:
        logger.exception(f"✗ Failed to regenerate questions for chapter {chapter_id}: {e}")
        db = DatabaseManager()
        db.update_chapter_question_status(chapter_id, 'error')


def question_generation_watcher():
    """
    Background watcher that monitors chapters and triggers question generation when tags are ready.
    Runs every 10 seconds to check for chapters with 'pending' status that have tags available.
    """
    logger.info("Started question generation watcher")
    
    while True:
        try:
            time.sleep(10)  # Check every 10 seconds
            
            db = DatabaseManager()
            
            # Find all chapters with 'pending' status
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            dc.id, 
                            dc.draft_id, 
                            dc.title, 
                            dc.content, 
                            dc.html_formatting,
                            db.age_range,
                            db.reading_level,
                            db.tag_status,
                            db.tags
                        FROM draft_chapters dc
                        JOIN draft_books db ON dc.draft_id = db.id
                        WHERE dc.question_status = 'pending'
                          AND db.tag_status = 'ready'
                          AND db.tags IS NOT NULL
                          AND jsonb_array_length(db.tags) > 0
                        ORDER BY dc.created_at ASC
                        LIMIT 5
                    """)
                    
                    pending_chapters = cur.fetchall()
            
            if pending_chapters:
                logger.info(f"Found {len(pending_chapters)} chapters ready for question generation")
                
                if PARALLEL_GENERATION:
                    # PARALLEL MODE: Process all chapters at once (faster but needs more GPU memory)
                    for chapter in pending_chapters:
                        chapter_id, draft_id, title, content, html_content, age_range, reading_level, tag_status, tags = chapter
                        
                        # Extract grade tags from tags array
                        grade_tags = [tag for tag in tags if tag.startswith('grade-')]
                        
                        if grade_tags:
                            logger.info(f"Triggering question generation for chapter {chapter_id} with grades: {grade_tags}")
                            
                            # Trigger async question generation in separate thread
                            thread = threading.Thread(
                                target=generate_questions_async,
                                args=(chapter_id, draft_id, title, content, html_content, age_range, reading_level)
                            )
                            thread.daemon = True
                            thread.start()
                        else:
                            logger.warning(f"Chapter {chapter_id} has tags but no grade tags found: {tags}")
                else:
                    # SEQUENTIAL MODE: Process one chapter at a time (GPU-limited environments)
                    # Only process the first pending chapter
                    chapter = pending_chapters[0]
                    chapter_id, draft_id, title, content, html_content, age_range, reading_level, tag_status, tags = chapter
                    
                    # Extract grade tags from tags array
                    grade_tags = [tag for tag in tags if tag.startswith('grade-')]
                    
                    if grade_tags:
                        logger.info(f"[SEQUENTIAL] Processing chapter {chapter_id} with grades: {grade_tags}")
                        
                        # Process synchronously - wait for completion
                        generate_questions_async(chapter_id, draft_id, title, content, html_content, age_range, reading_level)
                    else:
                        logger.warning(f"Chapter {chapter_id} has tags but no grade tags found: {tags}")
        
        except Exception as e:
            logger.exception(f"Error in question generation watcher: {e}")
            time.sleep(30)  # Wait longer after an error


def start_question_generation_watcher():
    """Start the question generation watcher in a daemon thread."""
    watcher_thread = threading.Thread(target=question_generation_watcher, daemon=True)
    watcher_thread.start()
    logger.info("Question generation watcher thread started")
