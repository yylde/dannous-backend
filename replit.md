# Kids Reading Platform - EPUB Processing Pipeline

## Project Overview

This is an EPUB processing pipeline for a kids reading platform. It downloads books from Project Gutenberg, splits them into chapters, generates comprehension questions, and stores everything in a PostgreSQL database.

## Recent Changes

### Draft System with Async Question Generation (October 12, 2025)

Implemented a complete draft system that allows incremental book processing with the ability to save work and continue later:

**Database Schema:**
- **book_drafts** - Tracks books in progress with metadata
- **draft_chapters** - Stores chapters with question generation status (pending, generating, ready, error)
- **draft_questions** - Comprehension questions for draft chapters
- **draft_vocabulary** - Vocabulary words and definitions for draft chapters

**Key Features:**
1. **Draft Selection Modal** - Shows on page load, allowing users to:
   - Download a new book (creates draft automatically)
   - Continue working on existing drafts
   
2. **Auto-Save as Draft** - Books are automatically saved as drafts when:
   - Downloaded from Project Gutenberg
   - Chapters are added

3. **Async Question Generation** - Questions generate in background using Python threading:
   - Status tracking: pending → generating → ready/error
   - No blocking UI while questions are being generated
   - Each chapter's status shown with colored badges

4. **Chapter Detail View** - Click on saved chapters to view:
   - Question generation status
   - Comprehension questions with difficulty levels
   - Vocabulary words with definitions and examples
   - Full chapter metadata

5. **Draft Finalization** - When complete:
   - "Finalize Book" button moves draft to main books table
   - All chapters and questions transferred atomically
   - Draft is marked as completed

**Workflow:**
1. User downloads book → auto-saved as draft
2. User adds chapters → each saved to draft with "generating" status
3. Questions generate asynchronously in background
4. User can view chapter details to see questions and status
5. When done, finalize to move to production books table

### Previous Changes (October 8, 2025)

### README Documentation Added

Created comprehensive README.md with local setup instructions:
- Prerequisites (Python 3.11+, PostgreSQL, Ollama)
- Step-by-step installation guide
- Environment variable configuration
- Database setup instructions
- Troubleshooting section
- Popular Gutenberg books for testing
- Feature explanations (automatic text selection, prominent headers, infinite scroll)

### Infinite Scroll Book Display

Redesigned the book view for better usability:
- **Removed pagination** - Book text now displays as infinite vertical scroll instead of page-by-page navigation
- **Reorganized layout** - Settings and chapter builder moved to top, book text in scrollable container below
- **Streamlined workflow** - Select text from full book view, add to chapter, and continue scrolling
- **Improved UX** - No more clicking through pages; all book content accessible in one view
- **Editable chapter content** - Click into the chapter field to edit, delete, or correct text
- **Dynamic target range** - Word count targets update automatically when reading level is changed

### Text Formatting Improvements

Updated text display formatting for better readability:
- **Reduced font size** from 1.05rem to 0.95rem for cleaner appearance
- **Improved paragraph spacing** with proper margins between paragraphs
- **Enhanced text flow** with justified alignment and optimized line height (1.7)
- **Prominent chapter headers** - Headings (h1-h6) preserved from EPUB and styled with:
  - Purple color (#667eea) and bold font weight
  - Larger font sizes (1.8rem for h1 down to 1rem for h5/h6)
  - Underline borders for h1 and h2
  - Extra spacing above/below for clear section breaks
- **Fixed EPUB parsing** to preserve heading tags from original EPUB files
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

**Production Tables:**
- **books** - Book metadata (title, author, age range, reading level, etc.)
- **chapters** - Chapter content and metadata
- **questions** - Comprehension questions with expected keywords

**Draft Tables:**
- **book_drafts** - Books in progress with metadata
- **draft_chapters** - Chapters with question status tracking
- **draft_questions** - Questions for draft chapters
- **draft_vocabulary** - Vocabulary for draft chapters

## User Preferences

The user prefers:
- Manual control over chapter splitting instead of AI automation
- Visual feedback for word count validation
- Simple, intuitive UI for book processing

## How to Use

### Admin UI (Recommended)

**Starting a New Book:**
1. Open the web interface (automatically opens on port 5000)
2. Choose "Download New Book" from the modal
3. Enter a Project Gutenberg book ID (e.g., 11115 for Alice in Wonderland)
4. Click "Download Book" - the book is automatically saved as a draft
5. Configure settings (age range, reading level, genre)
6. Select text from the book and add to current chapter
7. Give each chapter a title
8. Monitor word count (green = valid range, red = out of range)
9. Click "Finish Chapter" - questions will generate in background
10. Repeat for all chapters
11. Click "Finalize Book" when all chapters are complete

**Continuing an Existing Draft:**
1. Open the web interface
2. Choose "Continue Existing Draft" from the modal
3. Select a draft from the list
4. Continue adding chapters or review existing ones
5. Click on saved chapters to view questions and status
6. Click "Finalize Book" when ready

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
