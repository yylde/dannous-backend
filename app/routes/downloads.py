"""Routes for downloading and processing books."""

import re
import logging
import ollama
from flask import Blueprint, request, jsonify, current_app
from pathlib import Path
from uuid import uuid4

from src.epub_parser import download_gutenberg_epub, EPUBParser
from src.question_generator import QuestionGenerator
from src.database import DatabaseManager, inject_vocabulary_abbr
from src.models import Book, Chapter, Question, ProcessedBook
from src.config import settings
from src.chapter_splitter import calculate_reading_time
from app.utils.helpers import split_into_pages, extract_description

downloads_bp = Blueprint('downloads', __name__)
logger = logging.getLogger(__name__)


@downloads_bp.route('/download-book', methods=['POST'])
def download_book():
    """Download book from Project Gutenberg."""
    try:
        data = request.json
        gutenberg_id = data.get('gutenberg_id')
        
        if not gutenberg_id:
            return jsonify({'error': 'Gutenberg ID is required'}), 400
        
        logger.info(f"Downloading book {gutenberg_id}")
        
        DOWNLOAD_DIR = current_app.config['DOWNLOAD_DIR']
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


@downloads_bp.route('/save-chapters', methods=['POST'])
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


@downloads_bp.route('/generate-title', methods=['POST'])
def generate_title():
    """Generate chapter title using AI."""
    try:
        data = request.json
        content = data.get('content', '')
        
        if not content:
            return jsonify({'error': 'Content is required'}), 400
        
        logger.info("Generating AI title for chapter content")
        
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
