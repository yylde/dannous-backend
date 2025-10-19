#!/usr/bin/env python3
"""Flask admin UI for manual chapter splitting."""

import os
import re
import logging
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from pathlib import Path
from uuid import uuid4

from src.epub_parser import download_gutenberg_epub, EPUBParser
from src.question_generator import QuestionGenerator
from src.database import DatabaseManager, inject_vocabulary_abbr
from src.models import Book, Chapter, Question, ProcessedBook
from src.config import settings
from src.chapter_splitter import calculate_reading_time

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# DIFFICULTY_RANGES removed - word count validation is no longer enforced
# Reading levels are still used for AI question generation

@app.route('/')
def index():
    """Admin UI homepage."""
    return render_template('index.html')

@app.route('/api/download-book', methods=['POST'])
def download_book():
    """Download book from Project Gutenberg."""
    try:
        data = request.json
        gutenberg_id = data.get('gutenberg_id')
        
        if not gutenberg_id:
            return jsonify({'error': 'Gutenberg ID is required'}), 400
        
        logger.info(f"Downloading book {gutenberg_id}")
        
        filepath = download_gutenberg_epub(gutenberg_id, str(DOWNLOAD_DIR))
        
        parser = EPUBParser(filepath)
        epub_data = parser.parse()
        
        # Use plain text for UI display and word counting
        text = epub_data['raw_text']
        html = epub_data['raw_html']
        pages = split_into_pages(text)
        
        return jsonify({
            'success': True,
            'book_id': gutenberg_id,
            'title': epub_data['metadata']['title'],
            'author': epub_data['metadata']['author'],
            'full_text': text,
            'full_html': html,
            'pages': pages,
            'total_pages': len(pages),
            'metadata': epub_data['metadata']
        })
    
    except Exception as e:
        logger.exception("Download failed")
        return jsonify({'error': str(e)}), 500

@app.route('/api/save-chapters', methods=['POST'])
def save_chapters():
    """Save manually created chapters and generate questions."""
    try:
        data = request.json
        chapters_data = data.get('chapters', [])
        metadata = data.get('metadata', {})
        age_range = data.get('age_range', settings.default_age_range)
        reading_level = data.get('reading_level', settings.default_reading_level)
        genre = data.get('genre', settings.default_genre)
        
        if not chapters_data:
            return jsonify({'error': 'No chapters provided'}), 400
        
        logger.info(f"Saving {len(chapters_data)} chapters for '{metadata.get('title')}'")
        
        book_id = uuid4()
        total_words = sum(ch['word_count'] for ch in chapters_data)
        total_reading_time = sum(calculate_reading_time(ch['word_count']) for ch in chapters_data)
        
        description = extract_description(chapters_data[0]['content'] if chapters_data else "")
        
        book = Book(
            id=book_id,
            title=metadata.get('title', 'Untitled'),
            author=metadata.get('author', 'Unknown'),
            description=description,
            age_range=age_range,
            reading_level=reading_level,
            genre=genre,
            total_chapters=len(chapters_data),
            estimated_reading_time_minutes=total_reading_time,
            isbn=metadata.get('isbn'),
            publication_year=metadata.get('publication_year')
        )
        
        chapters = []
        questions = []
        
        generator = QuestionGenerator()
        
        for i, ch_data in enumerate(chapters_data, 1):
            chapter = Chapter(
                id=uuid4(),
                book_id=book_id,
                chapter_number=i,
                title=ch_data.get('title', f'Chapter {i}'),
                content=ch_data['content'],
                word_count=ch_data['word_count'],
                estimated_reading_time_minutes=calculate_reading_time(ch_data['word_count'])
            )
            chapters.append(chapter)
            
            logger.info(f"Generating questions for chapter {i}")
            questions_data, vocabulary_data, tags_data = generator.generate_questions(
                title=book.title,
                author=book.author,
                chapter_number=i,
                chapter_title=chapter.title,
                chapter_text=chapter.content,
                reading_level=reading_level,
                age_range=age_range,
                num_questions=settings.questions_per_chapter
            )
            chapter.vocabulary_words = vocabulary_data
            
            # Store tags on the book object (accumulate from first chapter)
            if i == 1 and tags_data:
                book.tags = tags_data
            
            chapter.html_formatting = inject_vocabulary_abbr(chapter.content, vocabulary_data)
            
            # UPDATED: Loop through questions (not questions_data directly)
            for j, q_data in enumerate(questions_data, 1):
                question = Question(
                    id=uuid4(),
                    book_id=book_id,
                    chapter_id=chapter.id,
                    question_text=q_data['text'],
                    question_type='comprehension',
                    difficulty_level=q_data.get('difficulty', 'medium'),
                    expected_keywords=q_data.get('keywords', []),
                    min_word_count=settings.min_answer_words,
                    max_word_count=settings.max_answer_words,
                    order_index=j
                )
                questions.append(question)
        
        processed_book = ProcessedBook(
            book=book,
            chapters=chapters,
            questions=questions
        )
        
        db = DatabaseManager()
        book_id_str, num_chapters, num_questions = db.insert_processed_book(processed_book)
        
        logger.info(f"Successfully saved book: {book_id_str}")
        
        return jsonify({
            'success': True,
            'book_id': book_id_str,
            'chapters_saved': num_chapters,
            'questions_generated': num_questions
        })
    
    except ValueError as e:
        return jsonify({'error': f'Duplicate book: {str(e)}'}), 400
    except Exception as e:
        logger.exception("Save failed")
        return jsonify({'error': str(e)}), 500

# Removed /api/difficulty-ranges endpoint - no longer validating word counts

@app.route('/api/generate-title', methods=['POST'])
def generate_title():
    """Generate chapter title using AI."""
    try:
        data = request.json
        content = data.get('content', '')
        
        if not content:
            return jsonify({'error': 'Content is required'}), 400
        
        logger.info("Generating AI title for chapter content")
        
        import ollama
        
        preview = ' '.join(content.split()[:200])
        
        prompt = f"""Based on this excerpt from a children's book, create a short, engaging chapter title (maximum 6 words).

The title should:
- Be appropriate for children
- Hint at what happens in this section
- Be intriguing but not a spoiler
- Be in title case

Excerpt:
{preview}

Respond with ONLY the title, nothing else. Do not include quotes or "Chapter X:" prefix."""

        response = ollama.generate(
            model=settings.ollama_model,
            prompt=prompt,
            options={'temperature': 0.7, 'num_predict': 20}
        )
        
        title = response['response'].strip()
        title = re.sub(r'^["\'`]+|["\'`]+$', '', title)
        title = re.sub(r'^(Chapter|Section)\s+\d+:?\s*', '', title, flags=re.IGNORECASE)
        
        words = title.split()
        if len(words) > 6:
            title = ' '.join(words[:6])
        
        return jsonify({'success': True, 'title': title})
    
    except Exception as e:
        logger.exception("Title generation failed")
        return jsonify({'error': str(e)}), 500

# ==================== DRAFT ENDPOINTS ====================

@app.route('/api/drafts', methods=['GET'])
def get_drafts():
    """Get all incomplete drafts."""
    try:
        db = DatabaseManager()
        drafts = db.get_all_drafts()
        return jsonify({'success': True, 'drafts': drafts})
    except Exception as e:
        logger.exception("Failed to get drafts")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>', methods=['GET'])
def get_draft(draft_id):
    """Get a specific draft with chapters."""
    try:
        db = DatabaseManager()
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        chapters = db.get_draft_chapters(draft_id)
        draft['chapters'] = chapters
        
        return jsonify({'success': True, 'draft': draft})
    except Exception as e:
        logger.exception("Failed to get draft")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft', methods=['POST'])
def create_or_update_draft():
    """Create or update a draft."""
    try:
        data = request.json
        draft_id = data.get('draft_id')
        
        db = DatabaseManager()
        
        if draft_id:
            # Update existing draft
            update_fields = {}
            for field in ['age_range', 'reading_level', 'genre', 'cover_image_url']:
                if field in data:
                    update_fields[field] = data[field]
            if update_fields:
                db.update_draft(draft_id, **update_fields)
            return jsonify({'success': True, 'draft_id': draft_id})
        else:
            # Create new draft - database connection closes automatically at end of context
            draft_id = db.create_draft(
                gutenberg_id=data.get('gutenberg_id'),
                title=data.get('title'),
                author=data.get('author'),
                full_text=data.get('full_text'),
                age_range=data.get('age_range', settings.default_age_range),
                reading_level=data.get('reading_level', settings.default_reading_level),
                genre=data.get('genre', settings.default_genre),
                cover_image_url=data.get('cover_image_url'),
                metadata=data.get('metadata', {}),
                full_html=data.get('full_html')
            )
            
            # Database connection is now closed and transaction committed
            # Safe to start async operations
            logger.info(f"Created draft {draft_id}, starting async tag generation...")
            
            # Trigger async tag generation in background thread
            # Transaction is guaranteed committed since db object is out of scope
            import threading
            
            thread = threading.Thread(
                target=generate_tags_async,
                args=(
                    draft_id,
                    data.get('title'),
                    data.get('author'),
                    data.get('full_text'),
                    data.get('age_range', settings.default_age_range),
                    data.get('reading_level', settings.default_reading_level)
                )
            )
            thread.daemon = True
            thread.start()
            
            logger.info(f"Started async tag generation for draft {draft_id}")
            
            return jsonify({'success': True, 'draft_id': draft_id})
    
    except Exception as e:
        logger.exception("Failed to save draft")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft-chapter', methods=['POST'])
def save_draft_chapter():
    """Save a chapter to draft. Question generation will be triggered by background watcher when tags are ready."""
    try:
        data = request.json
        draft_id = data.get('draft_id')
        chapter_number = data.get('chapter_number')
        title = data.get('title')
        content = data.get('content')
        html_content = data.get('html_content')
        word_count = data.get('word_count')
        
        if not all([draft_id, chapter_number, title, content]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        db = DatabaseManager()
        chapter_id = db.save_draft_chapter(
            draft_id=draft_id,
            chapter_number=chapter_number,
            title=title,
            content=content,
            word_count=word_count,
            html_formatting=html_content
        )
        
        # Note: Question generation is now handled by the background watcher
        # It will automatically trigger when tags are ready (either from AI or manual entry)
        logger.info(f"Saved chapter {chapter_id} for draft {draft_id}. Questions will generate when tags are ready.")
        
        return jsonify({
            'success': True,
            'chapter_id': chapter_id,
            'status': 'pending'  # Status will be updated by watcher
        })
    
    except Exception as e:
        logger.exception("Failed to save draft chapter")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft-chapters/<draft_id>', methods=['GET'])
def get_draft_chapters_status(draft_id):
    """Get all chapters for a draft with their current status (for polling)."""
    try:
        db = DatabaseManager()
        chapters = db.get_draft_chapters(draft_id)
        
        # Return only the data needed for status polling
        chapter_statuses = [
            {
                'id': ch['id'],
                'question_status': ch.get('question_status', 'pending')
            }
            for ch in chapters
        ]
        
        return jsonify({'success': True, 'chapters': chapter_statuses})
    except Exception as e:
        logger.exception("Failed to get draft chapters status")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft-chapter/<chapter_id>', methods=['GET'])
def get_draft_chapter_detail(chapter_id):
    """Get chapter details with questions and vocabulary."""
    try:
        db = DatabaseManager()
        chapter = db.get_draft_chapter(chapter_id)
        if not chapter:
            return jsonify({'error': 'Chapter not found'}), 404
        
        return jsonify({'success': True, 'chapter': chapter})
    except Exception as e:
        logger.exception("Failed to get chapter details")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft-chapter/<chapter_id>', methods=['DELETE'])
def delete_draft_chapter(chapter_id):
    """Delete a draft chapter."""
    try:
        db = DatabaseManager()
        deleted_data = db.delete_draft_chapter(chapter_id)
        if not deleted_data:
            return jsonify({'error': 'Chapter not found'}), 404
        
        return jsonify({
            'success': True,
            'content': deleted_data['content'],
            'chapter_number': deleted_data['chapter_number']
        })
    except Exception as e:
        logger.exception("Failed to delete chapter")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>', methods=['DELETE'])
def delete_draft(draft_id):
    """Delete a draft and all its associated data."""
    try:
        db = DatabaseManager()
        success = db.delete_draft(draft_id)
        if not success:
            return jsonify({'error': 'Draft not found'}), 404
        
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to delete draft")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft-tags-url/<draft_id>', methods=['PUT'])
def update_draft_tags_url(draft_id):
    """Update tags and cover URL for a draft."""
    try:
        data = request.json
        tags = data.get('tags', [])
        cover_image_url = data.get('cover_image_url', '')
        
        db = DatabaseManager()
        
        update_data = {
            'tags': tags,
            'cover_image_url': cover_image_url
        }
        
        db.update_draft(draft_id, update_data)
        
        return jsonify({
            'success': True,
            'message': 'Tags and cover URL updated successfully'
        })
    except Exception as e:
        logger.exception("Failed to update tags and URL")
        return jsonify({'error': str(e)}), 500

@app.route('/api/finalize-draft/<draft_id>', methods=['POST'])
def finalize_draft(draft_id):
    """Finalize draft and move to main books table."""
    try:
        db = DatabaseManager()
        book_id, chapters, questions = db.finalize_draft(draft_id)
        
        return jsonify({
            'success': True,
            'book_id': book_id,
            'chapters': chapters,
            'questions': questions
        })
    except Exception as e:
        logger.exception("Failed to finalize draft")
        return jsonify({'error': str(e)}), 500

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
                vocab_count=8  # 8 words per grade level
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
        
        logger.info(f"✓ Generated questions for {len(grade_levels)} grade levels with {len(all_vocabulary)} total vocabulary items")
        
    except Exception as e:
        logger.exception(f"Failed to generate questions for chapter {chapter_id}")
        db = DatabaseManager()
        db.update_chapter_question_status(chapter_id, 'error')

def generate_tags_async(draft_id, title, author, full_text, age_range, reading_level):
    """Generate tags asynchronously in background for a book."""
    try:
        db = DatabaseManager()
        db.update_draft_tag_status(draft_id, 'generating')
        
        generator = QuestionGenerator()
        tags_data = generator.generate_tags(
            title=title,
            author=author,
            book_text=full_text,
            reading_level=reading_level or settings.default_reading_level,
            age_range=age_range or settings.default_age_range
        )
        
        # Save tags to the draft (even if using fallback)
        if tags_data and len(tags_data) > 0:
            db.update_draft(draft_id, tags=tags_data)
            db.update_draft_tag_status(draft_id, 'ready')
            logger.info(f"✓ Generated {len(tags_data)} tags for draft {draft_id}: {tags_data}")
        else:
            db.update_draft_tag_status(draft_id, 'error')
            logger.error(f"✗ No tags generated for draft {draft_id}")
        
    except Exception as e:
        logger.exception(f"✗ Failed to generate tags for draft {draft_id}: {e}")
        db = DatabaseManager()
        # Even on error, try to save fallback tags if they exist
        try:
            generator = QuestionGenerator()
            fallback_tags = generator._generate_fallback_tags(reading_level or settings.default_reading_level)
            if fallback_tags:
                db.update_draft(draft_id, tags=fallback_tags)
                db.update_draft_tag_status(draft_id, 'ready')
                logger.warning(f"⚠ Used fallback tags for draft {draft_id}: {fallback_tags}")
            else:
                db.update_draft_tag_status(draft_id, 'error')
        except:
            db.update_draft_tag_status(draft_id, 'error')

def split_into_pages(text, words_per_page=500):
    """Split text into pages for easier navigation, preserving paragraph structure."""
    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
    pages = []
    current_page = []
    current_word_count = 0
    
    for para in paragraphs:
        para_words = len(para.split())
        
        if current_word_count + para_words > words_per_page and current_page:
            pages.append('\n\n'.join(current_page))
            current_page = [para]
            current_word_count = para_words
        else:
            current_page.append(para)
            current_word_count += para_words
    
    if current_page:
        pages.append('\n\n'.join(current_page))
    
    return pages if pages else [text]

def extract_description(text, max_length=500):
    """Extract description from text."""
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    for para in paragraphs[:3]:
        if len(para) >= 50:
            description = para
            if len(description) > max_length:
                description = description[:max_length].rsplit(' ', 1)[0] + '...'
            return description
    
    return "No description available."

# ==================== BACKGROUND WATCHER ====================

def question_generation_watcher():
    """
    Background watcher that monitors chapters and triggers question generation when tags are ready.
    Runs every 10 seconds to check for chapters with 'pending' status that have tags available.
    """
    import threading
    import time
    
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
                        JOIN draft_book db ON dc.draft_id = db.id
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
                
                for chapter in pending_chapters:
                    chapter_id, draft_id, title, content, html_content, age_range, reading_level, tag_status, tags = chapter
                    
                    # Extract grade tags from tags array
                    grade_tags = [tag for tag in tags if tag.startswith('grade-')]
                    
                    if grade_tags:
                        logger.info(f"Triggering question generation for chapter {chapter_id} with grades: {grade_tags}")
                        
                        # Trigger async question generation
                        thread = threading.Thread(
                            target=generate_questions_async,
                            args=(chapter_id, draft_id, title, content, html_content, age_range, reading_level)
                        )
                        thread.daemon = True
                        thread.start()
                    else:
                        logger.warning(f"Chapter {chapter_id} has tags but no grade tags found: {tags}")
        
        except Exception as e:
            logger.exception(f"Error in question generation watcher: {e}")
            time.sleep(30)  # Wait longer after an error

def start_question_generation_watcher():
    """Start the question generation watcher in a daemon thread."""
    import threading
    watcher_thread = threading.Thread(target=question_generation_watcher, daemon=True)
    watcher_thread.start()
    logger.info("Question generation watcher thread started")

# Start the watcher when the module is loaded
start_question_generation_watcher()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
