#!/usr/bin/env python3
"""Flask admin UI for manual chapter splitting."""

import os
import re
import logging
import atexit
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
from src.ollama_queue import shutdown_queue_manager

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_queue():
    """Cleanup queue manager on shutdown."""
    logger.info("Shutting down Ollama queue manager...")
    shutdown_queue_manager(wait=True, timeout=30.0)

atexit.register(cleanup_queue)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# DIFFICULTY_RANGES removed - word count validation is no longer enforced
# Reading levels are still used for AI question generation

# Control parallel vs sequential question generation
# Set PARALLEL_GENERATION=false for GPU-limited environments
PARALLEL_GENERATION = os.environ.get('PARALLEL_GENERATION', 'true').lower() == 'true'
logger.info(f"Question generation mode: {'PARALLEL' if PARALLEL_GENERATION else 'SEQUENTIAL'}")

@app.route('/')
def index():
    """Admin UI homepage."""
    return render_template('index.html')

@app.route('/queue')
def queue_page():
    """Queue monitoring page."""
    return render_template('queue.html')

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
            # Check if a draft with this Gutenberg ID already exists
            # Normalize the input (strip whitespace, convert to int)
            gutenberg_id = data.get('gutenberg_id')
            if gutenberg_id:
                # Normalize to integer to avoid string formatting issues
                try:
                    gutenberg_id = int(str(gutenberg_id).strip())
                except (ValueError, TypeError):
                    pass
                existing_draft = db.get_draft_by_gutenberg_id(gutenberg_id)
                if existing_draft:
                    logger.info(f"Draft with Gutenberg ID {gutenberg_id} already exists: {existing_draft['id']}")
                    return jsonify({
                        'error': f"A draft for this book already exists: '{existing_draft['title']}' by {existing_draft['author']}",
                        'existing_draft_id': existing_draft['id']
                    }), 409
            
            # Calculate word count
            full_text = data.get('full_text', '')
            word_count = len(full_text.split()) if full_text else 0
            
            # Create new draft - database connection closes automatically at end of context
            draft_id = db.create_draft(
                gutenberg_id=data.get('gutenberg_id'),
                title=data.get('title'),
                author=data.get('author'),
                full_text=full_text,
                age_range=data.get('age_range', settings.default_age_range),
                reading_level=data.get('reading_level', settings.default_reading_level),
                genre=data.get('genre', settings.default_genre),
                cover_image_url=data.get('cover_image_url'),
                metadata=data.get('metadata', {}),
                full_html=data.get('full_html'),
                word_count=word_count
            )
            
            # Database connection is now closed and transaction committed
            # Safe to start async operations
            logger.info(f"Created draft {draft_id}, starting async tag and description generation...")
            
            # Trigger async tag generation in background thread
            # Transaction is guaranteed committed since db object is out of scope
            import threading
            
            tag_thread = threading.Thread(
                target=generate_tags_async,
                args=(
                    draft_id,
                    data.get('title'),
                    data.get('author'),
                    data.get('age_range', settings.default_age_range),
                    data.get('reading_level', settings.default_reading_level)
                )
            )
            tag_thread.daemon = True
            tag_thread.start()
            
            logger.info(f"Started async tag generation for draft {draft_id}")
            
            # Trigger async description generation in background thread
            book_text_sample = ' '.join(full_text.split()[:2000]) if full_text else ''
            description_thread = threading.Thread(
                target=generate_description_async,
                args=(
                    draft_id,
                    data.get('title'),
                    data.get('author'),
                    book_text_sample
                )
            )
            description_thread.daemon = True
            description_thread.start()
            
            logger.info(f"Started async description generation for draft {draft_id}")
            
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

@app.route('/api/chapter/<chapter_id>', methods=['PUT'])
def update_chapter(chapter_id):
    """Update a draft chapter's content and HTML."""
    try:
        data = request.json
        db = DatabaseManager()
        
        success = db.update_draft_chapter(
            chapter_id,
            title=data.get('title'),
            content=data.get('content'),
            html_formatting=data.get('html_formatting')
        )
        
        if not success:
            return jsonify({'error': 'Chapter not found or no changes made'}), 404
        
        return jsonify({'success': True, 'message': 'Chapter updated successfully'})
    except Exception as e:
        logger.exception("Failed to update chapter")
        return jsonify({'error': str(e)}), 500

@app.route('/api/question/<question_id>', methods=['PUT'])
def update_question(question_id):
    """Update a draft question."""
    try:
        data = request.json
        db = DatabaseManager()
        db.update_question(
            question_id,
            data.get('question_text'),
            data.get('question_type'),
            data.get('difficulty_level'),
            data.get('expected_keywords', []),
            data.get('min_word_count'),
            data.get('max_word_count')
        )
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to update question")
        return jsonify({'error': str(e)}), 500

@app.route('/api/question/<question_id>', methods=['DELETE'])
def delete_question(question_id):
    """Delete a draft question."""
    try:
        db = DatabaseManager()
        db.delete_question(question_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to delete question")
        return jsonify({'error': str(e)}), 500

@app.route('/api/vocabulary/<vocab_id>', methods=['PUT'])
def update_vocabulary(vocab_id):
    """Update a draft vocabulary item."""
    try:
        data = request.json
        db = DatabaseManager()
        db.update_vocabulary(
            vocab_id,
            data.get('word'),
            data.get('definition'),
            data.get('example', '')
        )
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to update vocabulary")
        return jsonify({'error': str(e)}), 500

@app.route('/api/vocabulary/<vocab_id>', methods=['DELETE'])
def delete_vocabulary(vocab_id):
    """Delete a draft vocabulary item."""
    try:
        db = DatabaseManager()
        db.delete_vocabulary(vocab_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Failed to delete vocabulary")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft-tags-url/<draft_id>', methods=['PUT'])
def update_draft_tags_url(draft_id):
    """Update tags and cover URL for a draft."""
    try:
        data = request.json
        tags = data.get('tags', [])
        cover_image_url = data.get('cover_image_url', '')
        
        db = DatabaseManager()
        
        # Update draft with unpacked keyword arguments
        db.update_draft(draft_id, tags=tags, cover_image_url=cover_image_url)
        
        return jsonify({
            'success': True,
            'message': 'Tags and cover URL updated successfully'
        })
    except Exception as e:
        logger.exception("Failed to update tags and URL")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>/regenerate-tags', methods=['POST'])
def regenerate_tags(draft_id):
    """Regenerate tags for a draft using AI."""
    try:
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Check if tag generation is already in progress
        current_tag_status = draft.get('tag_status')
        if current_tag_status in ('pending', 'generating'):
            logger.info(f"Blocked duplicate tag regeneration request for draft {draft_id} (current status: {current_tag_status})")
            return jsonify({
                'error': 'Tag generation already in progress. Please wait for it to complete.'
            }), 409
        
        # Set tag status to pending
        db.update_draft_tag_status(draft_id, 'pending')
        
        # Start async tag generation
        import threading
        thread = threading.Thread(
            target=generate_tags_async,
            args=(
                draft_id,
                draft.get('title'),
                draft.get('author'),
                draft.get('age_range'),
                draft.get('reading_level')
            )
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Started tag regeneration for draft {draft_id}")
        
        return jsonify({
            'success': True,
            'message': 'Tag regeneration started'
        })
    except Exception as e:
        logger.exception("Failed to start tag regeneration")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>/marker', methods=['PUT'])
def update_marker_position(draft_id):
    """Update the marker position for a draft."""
    try:
        data = request.json
        marker_position = data.get('marker_position')
        
        if marker_position is None:
            return jsonify({'error': 'marker_position is required'}), 400
        
        db = DatabaseManager()
        db.update_draft(draft_id, last_marker_position=marker_position)
        
        return jsonify({
            'success': True,
            'message': 'Marker position saved'
        })
    except Exception as e:
        logger.exception("Failed to update marker position")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>/usage', methods=['GET'])
def get_text_usage(draft_id):
    """Analyze which parts of the book text have been used in chapters using fuzzy matching."""
    try:
        from rapidfuzz import fuzz
        from rapidfuzz.distance import Levenshtein
        from bs4 import BeautifulSoup
        
        db = DatabaseManager()
        
        # Get the draft
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # CRITICAL: Use full_html to match frontend display, fallback to full_text
        book_text = draft.get('full_html') or draft.get('full_text', '')
        if not book_text:
            return jsonify({'used_paragraphs': []})
        
        # Split book into paragraphs (same way as frontend does)
        book_paragraphs = [p.strip() for p in book_text.split('\n\n') if p.strip()]
        
        logger.info(f"Usage tracking for draft {draft_id}: {len(book_paragraphs)} total paragraphs")
        
        # Get all chapters
        chapters = db.get_draft_chapters(draft_id)
        if not chapters:
            return jsonify({'used_paragraphs': []})
        
        # Track which paragraphs are used and which chapter they belong to
        used_paragraph_indices = set()
        paragraph_to_chapter = {}  # Maps paragraph_index -> chapter_number
        
        # Helper function to normalize text for comparison
        def normalize(text):
            """Normalize text for fuzzy matching - strip HTML, lowercase, remove extra whitespace."""
            # Strip HTML tags using BeautifulSoup
            soup = BeautifulSoup(text, 'html.parser')
            clean_text = soup.get_text(separator=' ')
            # Normalize whitespace and lowercase
            return ' '.join(clean_text.lower().split())
        
        # Normalize paragraphs once (for performance)
        normalized_paragraphs = [normalize(p) for p in book_paragraphs]
        logger.info(f"Normalized {len(normalized_paragraphs)} book paragraphs for matching")
        
        # For each chapter, find matching paragraphs in the book
        for chapter in chapters:
            chapter_text = chapter.get('content', '')
            chapter_number = chapter.get('chapter_number')
            if not chapter_text or chapter_number is None:
                continue
            
            # Split chapter into paragraphs (to compare paragraph-to-paragraph)
            chapter_paragraphs = [p.strip() for p in chapter_text.split('\n\n') if p.strip()]
            normalized_chapter_paras = [normalize(p) for p in chapter_paragraphs]
            
            # Check each book paragraph against each chapter paragraph
            for para_idx, normalized_para in enumerate(normalized_paragraphs):
                if para_idx in used_paragraph_indices:
                    continue  # Already marked as used
                    
                # Skip empty paragraphs
                if not normalized_para:
                    continue
                
                # Compare against each paragraph in the chapter
                # Use Levenshtein similarity with token-based fallback
                for chapter_para in normalized_chapter_paras:
                    if not chapter_para:
                        continue
                        
                    # HYBRID APPROACH: Levenshtein + token-based
                    # 1. Normalized Levenshtein similarity (order-aware, edit-tolerant)
                    leven_sim = Levenshtein.normalized_similarity(normalized_para, chapter_para) * 100
                    
                    # 2. Token-based similarity (vocabulary-aware)
                    token_sim = fuzz.token_sort_ratio(normalized_para, chapter_para)
                    
                    # Use weighted average: favor Levenshtein slightly for order preservation
                    # 60% Levenshtein + 40% token = better balance
                    combined_score = (leven_sim * 0.6) + (token_sim * 0.4)
                    
                    # 78% threshold allows minor edits while filtering different text
                    if combined_score >= 78:
                        used_paragraph_indices.add(para_idx)
                        paragraph_to_chapter[para_idx] = chapter_number
                        break  # Found a match, no need to check other chapter paragraphs
        
        return jsonify({
            'used_paragraphs': sorted(list(used_paragraph_indices)),
            'paragraph_chapters': paragraph_to_chapter  # Maps paragraph_index -> chapter_number
        })
        
    except Exception as e:
        logger.exception("Failed to analyze text usage")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>/description', methods=['PUT'])
def update_description(draft_id):
    """Update draft description manually."""
    try:
        data = request.json
        description = data.get('description', '').strip()
        
        db = DatabaseManager()
        
        # Verify draft exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Update description
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_books 
                    SET description = %s, description_status = 'ready', updated_at = NOW()
                    WHERE id = %s
                """, (description, draft_id))
        
        logger.info(f"Updated description for draft {draft_id}")
        
        return jsonify({
            'success': True,
            'message': 'Description updated successfully'
        })
    except Exception as e:
        logger.exception("Failed to update description")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>/generate-description', methods=['POST'])
def generate_description(draft_id):
    """Generate a book description using AI, auto-generating synopsis from book content."""
    try:
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Check if description generation is already actively generating
        # Allow retrying if stuck at "pending" (thread may have failed)
        current_description_status = draft.get('description_status')
        if current_description_status == 'generating':
            logger.info(f"Blocked duplicate description generation request for draft {draft_id} (currently generating)")
            return jsonify({
                'error': 'Description generation already in progress. Please wait for it to complete.'
            }), 409
        
        # If stuck at "pending", allow retry and log it
        if current_description_status == 'pending':
            logger.warning(f"Retrying stuck 'pending' description generation for draft {draft_id}")
        
        # Set description status to pending
        db.update_draft_description_status(draft_id, 'pending')
        
        # Extract book text sample (first 2000 words) for async processing
        book_text = draft.get('full_text') or draft.get('full_html', '')
        words = book_text.split()
        book_text_sample = ' '.join(words[:2000]) if words else ''
        
        # Start async description generation
        import threading
        thread = threading.Thread(
            target=generate_description_async,
            args=(
                draft_id,
                draft.get('title'),
                draft.get('author'),
                book_text_sample
            )
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Started description generation for draft {draft_id}")
        
        return jsonify({
            'success': True,
            'message': 'Description generation started'
        })
    except Exception as e:
        logger.exception("Failed to start description generation")
        return jsonify({'error': str(e)}), 500

@app.route('/api/draft/<draft_id>/regenerate-questions', methods=['POST'])
def regenerate_questions(draft_id):
    """Regenerate questions for a draft based on grade tag changes."""
    try:
        db = DatabaseManager()
        
        # Get the draft to verify it exists
        draft = db.get_draft(draft_id)
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Get all chapters for this draft
        chapters = db.get_draft_chapters(draft_id)
        if not chapters:
            return jsonify({'error': 'No chapters found for this draft'}), 400
        
        # Start async regeneration
        import threading
        thread = threading.Thread(
            target=regenerate_questions_for_draft_async,
            args=(draft_id,)
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Started question regeneration for draft {draft_id}")
        
        return jsonify({
            'success': True,
            'message': 'Question regeneration started'
        })
    except Exception as e:
        logger.exception("Failed to start question regeneration")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chapter/<chapter_id>/regenerate-questions', methods=['POST'])
def regenerate_chapter_questions(chapter_id):
    """Regenerate questions for a single chapter."""
    try:
        db = DatabaseManager()
        
        # Get the chapter to verify it exists and get draft_id
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, draft_id, title, content, html_formatting, word_count, question_status
                    FROM draft_chapters
                    WHERE id = %s
                """, (chapter_id,))
                result = cur.fetchone()
                
                if not result:
                    return jsonify({'error': 'Chapter not found'}), 404
                
                chapter_data = {
                    'id': str(result[0]),
                    'draft_id': str(result[1]),
                    'title': result[2],
                    'content': result[3],
                    'html_formatting': result[4],
                    'word_count': result[5],
                    'question_status': result[6]
                }
        
        # Atomically set status to 'generating' to prevent duplicate requests
        # This UPDATE will only succeed if the current status is NOT 'generating'
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE draft_chapters 
                    SET question_status = 'generating',
                        has_questions = false
                    WHERE id = %s AND question_status != 'generating'
                    RETURNING id
                """, (chapter_id,))
                result = cur.fetchone()
                
                # If no rows were updated, it means status was already 'generating'
                if not result:
                    logger.info(f"Blocked duplicate question regeneration request for chapter {chapter_id} (already generating)")
                    return jsonify({
                        'error': 'Question generation already in progress for this chapter. Please wait for it to complete.'
                    }), 409
        
        # Get the draft to get age_range and reading_level
        draft = db.get_draft(chapter_data['draft_id'])
        if not draft:
            return jsonify({'error': 'Draft not found'}), 404
        
        # Start async regeneration for this chapter
        import threading
        thread = threading.Thread(
            target=regenerate_single_chapter_questions_async,
            args=(
                chapter_data['id'],
                chapter_data['draft_id'],
                chapter_data['title'],
                chapter_data['content'],
                chapter_data['html_formatting'],
                draft.get('age_range'),
                draft.get('reading_level')
            )
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Started question regeneration for chapter {chapter_id}")
        
        return jsonify({
            'success': True,
            'message': 'Question regeneration started for chapter'
        })
    except Exception as e:
        logger.exception("Failed to start chapter question regeneration")
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

@app.route('/api/queue/status', methods=['GET'])
def get_queue_status():
    """Get current status of the Ollama queue."""
    try:
        from src.ollama_queue import get_queue_manager
        manager = get_queue_manager()
        queue_info = manager.get_queue_info()
        
        return jsonify({
            'success': True,
            'queue': queue_info
        })
    except Exception as e:
        logger.exception("Failed to get queue status")
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/flush', methods=['POST'])
def flush_queue():
    """Flush all pending tasks from the Ollama queue."""
    try:
        from src.ollama_queue import get_queue_manager
        manager = get_queue_manager()
        flushed_count = manager.flush_queue()
        
        logger.info(f"Queue flushed: {flushed_count} tasks removed")
        
        return jsonify({
            'success': True,
            'flushed_count': flushed_count,
            'message': f'Flushed {flushed_count} tasks from queue'
        })
    except Exception as e:
        logger.exception("Failed to flush queue")
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
        db = DatabaseManager()
        
        # Get the draft with current tags
        draft = db.get_draft(draft_id)
        if not draft:
            logger.error(f"Draft {draft_id} not found")
            return
        
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
        
        # Delete questions for removed grades (this happens even if no new grades are added)
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
        
        # Generate questions for new grades
        if grades_to_add:
            logger.info(f"Generating questions for new grades: {grades_to_add}")
            
            generator = QuestionGenerator()
            
            if not PARALLEL_GENERATION:
                logger.info(f"[SEQUENTIAL MODE] Processing {len(chapters)} chapters one at a time")
            else:
                logger.info(f"[PARALLEL MODE] Processing all {len(chapters)} chapters in parallel")
                # In parallel mode, set ALL chapters to 'generating' immediately for UI feedback
                for chapter in chapters:
                    db.update_chapter_question_status(chapter['id'], 'generating')
            
            chapters_to_process = chapters
            
            # Process each chapter
            for chapter in chapters_to_process:
                chapter_id = chapter['id']
                logger.info(f"Processing chapter {chapter['chapter_number']}: {chapter['title']}")
                
                # Update status to generating
                db.update_chapter_question_status(chapter_id, 'generating')
                
                all_vocabulary = []
                
                # Generate questions for each new grade level
                for grade_level in grades_to_add:
                    logger.info(f"  Generating for {grade_level}...")
                    
                    questions_data, vocabulary_data = generator.generate_questions(
                        title=draft.get('title', 'Book Draft'),
                        author=draft.get('author', 'Unknown'),
                        chapter_number=chapter['chapter_number'],
                        chapter_title=chapter['title'],
                        chapter_text=chapter['content'],
                        reading_level=draft.get('reading_level') or settings.default_reading_level,
                        age_range=draft.get('age_range') or settings.default_age_range,
                        grade_level=grade_level,
                        num_questions=settings.questions_per_chapter,
                        vocab_count=8,
                        book_id=str(draft_id),
                        chapter_id=str(chapter['id'])
                    )
                    
                    # Add grade_level to vocabulary items
                    for vocab_item in vocabulary_data:
                        vocab_item['grade_level'] = grade_level
                    
                    all_vocabulary.extend(vocabulary_data)
                    
                    # Save questions for this grade level
                    db.save_draft_questions(chapter_id, draft_id, questions_data, vocabulary_data, grade_level=grade_level)
                    
                    logger.info(f"  ✓ Saved {len(questions_data)} questions and {len(vocabulary_data)} vocabulary for {grade_level}")
                
                # Update HTML with vocabulary if we added new vocabulary
                if all_vocabulary and chapter.get('html_formatting'):
                    html_with_abbr = inject_vocabulary_abbr(chapter['html_formatting'], all_vocabulary)
                    
                    with db.get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE draft_chapters 
                                SET html_formatting = %s
                                WHERE id = %s
                            """, (html_with_abbr, chapter_id))
                
                # Mark chapter as ready
                db.update_chapter_question_status(chapter_id, 'ready')
        
        logger.info(f"✓ Question regeneration complete for draft {draft_id}")
        
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

def generate_tags_async(draft_id, title, author, age_range, reading_level):
    """Generate tags asynchronously in background for a book."""
    try:
        db = DatabaseManager()
        db.update_draft_tag_status(draft_id, 'generating')
        
        generator = QuestionGenerator()
        tags_data = generator.generate_tags(
            title=title,
            author=author,
            reading_level=reading_level or settings.default_reading_level,
            age_range=age_range or settings.default_age_range,
            book_id=str(draft_id)
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

def generate_description_async(draft_id, title, author, book_text_sample):
    """Generate description asynchronously in background for a book."""
    try:
        db = DatabaseManager()
        db.update_draft_description_status(draft_id, 'generating')
        
        generator = QuestionGenerator()
        description = generator.generate_description(
            title=title,
            author=author,
            book_text_sample=book_text_sample if book_text_sample else None,
            book_id=str(draft_id)
        )
        
        # Save description to the draft
        if description:
            db.update_draft(draft_id, description=description)
            db.update_draft_description_status(draft_id, 'ready')
            logger.info(f"✓ Generated description for draft {draft_id}: {description[:100]}...")
        else:
            db.update_draft_description_status(draft_id, 'error')
            logger.error(f"✗ No description generated for draft {draft_id}")
        
    except Exception as e:
        logger.exception(f"✗ Failed to generate description for draft {draft_id}: {e}")
        db = DatabaseManager()
        db.update_draft_description_status(draft_id, 'error')

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
    import threading
    watcher_thread = threading.Thread(target=question_generation_watcher, daemon=True)
    watcher_thread.start()
    logger.info("Question generation watcher thread started")

# Start the watcher when the module is loaded
start_question_generation_watcher()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
