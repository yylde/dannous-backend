# Kids Reading Platform - EPUB Processing Pipeline

## Project Overview

This is an EPUB processing pipeline for a kids reading platform. It downloads books from Project Gutenberg, splits them into chapters, generates comprehension questions, and stores everything in a PostgreSQL database.

## Recent Changes (October 8, 2025)

### Text Formatting Improvements

Updated text display formatting for better readability:
- **Reduced font size** from 1.05rem to 0.95rem for cleaner appearance
- **Improved paragraph spacing** with proper margins between paragraphs
- **Enhanced text flow** with justified alignment and optimized line height (1.7)
- **Fixed EPUB parsing** to better handle paragraph structure and remove weird line breaks
- Applied improvements to both book view and chapter preview areas

### Admin UI for Manual Chapter Splitting

Replaced the AI-based chapter splitter with a manual admin UI because the AI wasn't doing a great job. The new UI allows administrators to:

- **Input Gutenberg book ID** and download books directly
- **Display books page-by-page** for easier navigation
- **Manually select chapters** with visual word count tracking
- **Difficulty level validation** with color-coded indicators (red/green) based on word count ranges
- **Save chapters** and automatically send them to AI for question generation

### Features

1. **Flask Web Application** (`app.py`)
   - REST API for downloading books, saving chapters
   - Integrates with existing question generation pipeline
   - Word count validation based on difficulty levels

2. **Responsive Admin UI** (`templates/index.html`, `static/`)
   - Clean, modern interface for book processing
   - Real-time word count tracking
   - Visual validation of chapter lengths
   - Page-by-page navigation

3. **Difficulty Ranges**
   - Beginner: 300-800 words per chapter
   - Intermediate: 800-1,500 words per chapter
   - Advanced: 1,500-2,500 words per chapter

## Architecture

### Core Components

- **EPUB Parser** (`src/epub_parser.py`) - Downloads and extracts text from Project Gutenberg
- **Question Generator** (`src/question_generator.py`) - Uses Ollama LLM to generate comprehension questions
- **Database Manager** (`src/database.py`) - Handles PostgreSQL operations
- **Admin UI** (Flask app) - Manual chapter splitting interface

### Database Schema

- **books** - Book metadata (title, author, age range, reading level, etc.)
- **chapters** - Chapter content and metadata
- **questions** - Comprehension questions with expected keywords

## User Preferences

The user prefers:
- Manual control over chapter splitting instead of AI automation
- Visual feedback for word count validation
- Simple, intuitive UI for book processing

## How to Use

### Admin UI (Recommended)

1. Open the web interface (automatically opens on port 5000)
2. Enter a Project Gutenberg book ID (e.g., 11115 for Alice in Wonderland)
3. Click "Download Book"
4. Configure settings (age range, reading level, genre)
5. Navigate through pages and add them to chapters
6. Give each chapter a title
7. Monitor word count (green = valid range, red = out of range)
8. Click "Finish Chapter" when complete
9. Repeat for all chapters
10. Click "Save Book & Generate Questions" when done

### CLI (Legacy)

```bash
# Process a book from Gutenberg
python cli.py process-gutenberg 11115 --age-range "8-12" --reading-level "beginner"

# Test database connection
python cli.py test-db

# List books
python cli.py list-books
```

## Environment Variables

The following environment variables are automatically configured:
- `DATABASE_URL` - PostgreSQL connection string
- `OLLAMA_BASE_URL` - Ollama LLM endpoint (default: http://localhost:11434)
- `OLLAMA_MODEL` - LLM model to use (default: llama3.2)

## Dependencies

- Python 3.11
- Flask (web framework)
- PostgreSQL (database)
- Ollama (for question generation)
- Other dependencies in `requirements.txt`

## Project Structure

```
.
├── app.py                 # Flask web application
├── cli.py                 # Command-line interface (legacy)
├── src/
│   ├── epub_parser.py     # EPUB download and parsing
│   ├── question_generator.py  # AI question generation
│   ├── database.py        # Database operations
│   ├── models.py          # Data models
│   └── config.py          # Configuration
├── templates/
│   └── index.html         # Admin UI template
├── static/
│   ├── css/style.css      # Styling
│   └── js/app.js          # Frontend logic
└── schema.sql             # Database schema
```

## Notes

- The admin UI runs on port 5000
- Ollama must be running for question generation to work
- Books are downloaded to the `downloads/` directory
- All data is stored in PostgreSQL with CASCADE delete for data integrity
