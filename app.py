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
from src.database import DatabaseManager
from src.models import Book, Chapter, Question, ProcessedBook
from src.config import settings
from src.chapter_splitter import calculate_reading_time

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

DIFFICULTY_RANGES = {
    "beginner": {"min": 300, "max": 800},
    "intermediate": {"min": 800, "max": 1500},
    "advanced": {"min": 1500, "max": 2500}
}

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
        
        text = epub_data['raw_text']
        pages = split_into_pages(text)
        
        return jsonify({
            'success': True,
            'book_id': gutenberg_id,
            'title': epub_data['metadata']['title'],
            'author': epub_data['metadata']['author'],
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
            questions_data = generator.generate_questions(
                title=book.title,
                author=book.author,
                chapter_number=i,
                chapter_title=chapter.title,
                chapter_text=chapter.content,
                reading_level=reading_level,
                age_range=age_range,
                num_questions=settings.questions_per_chapter
            )
            
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

@app.route('/api/difficulty-ranges', methods=['GET'])
def get_difficulty_ranges():
    """Get word count ranges for each difficulty level."""
    return jsonify(DIFFICULTY_RANGES)

def split_into_pages(text, words_per_page=500):
    """Split text into pages for easier navigation."""
    paragraphs = re.split(r'\n\n+', text)
    pages = []
    current_page = []
    current_word_count = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
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
    
    return pages

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
