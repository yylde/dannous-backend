# EPUB Processing Pipeline for Kids Reading Platform

A CLI tool to process Project Gutenberg EPUB files and insert them into the reading platform database.

## Overview

This pipeline downloads EPUB files from Project Gutenberg, extracts and cleans text content, splits books into age-appropriate chapters, generates comprehension questions using a local Ollama LLM, and inserts everything into the PostgreSQL database.

## Features

- ✅ Download EPUBs from Project Gutenberg or process local files
- ✅ Extract and clean text (remove PG boilerplate)
- ✅ Intelligent chapter splitting based on reading level
- ✅ AI-generated comprehension questions (3 per chapter, open-ended)
- ✅ Direct database insertion matching existing schema
- ✅ CLI-only interface (no frontend)
- ✅ Robust error handling and logging

## Prerequisites

### Required Software
- **Python 3.9+**
- **PostgreSQL** (from main reading platform)
- **Ollama** (local LLM server)

### Install Ollama

**Linux/macOS:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:**
Download from https://ollama.com/download

**Start and pull model:**
```bash
# Start Ollama service (runs on port 11434)
ollama serve

# In another terminal, pull recommended model
ollama pull llama3.2
```

## Installation

```bash
# Clone this repository
git clone <your-epub-pipeline-repo>
cd epub-processing-pipeline

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your database credentials
nano .env
```

## Configuration

Edit `.env` file:

```env
# Database (same as main reading platform)
DATABASE_URL=postgresql://user:pass@localhost:5432/reading_platform

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Processing defaults
DEFAULT_AGE_RANGE=8-12
DEFAULT_READING_LEVEL=intermediate
MAX_CHAPTER_WORDS=1500
```

## Database Schema Reference

The pipeline inserts into these tables from your existing schema:

### books
```sql
- id: UUID (primary key, auto-generated)
- title: VARCHAR(500)
- author: VARCHAR(300)
- description: TEXT
- age_range: VARCHAR(20) - e.g., "8-12"
- reading_level: VARCHAR(20) - e.g., "intermediate"
- genre: VARCHAR(100)
- total_chapters: INTEGER
- estimated_reading_time_minutes: INTEGER
- cover_image_url: VARCHAR(500)
- isbn: VARCHAR(20)
- publication_year: INTEGER
- content_rating: VARCHAR(20)
- tags: JSONB (default '[]')
- is_active: BOOLEAN (default true)
- created_at: TIMESTAMP (default NOW())
```

### chapters
```sql
- id: UUID (primary key, auto-generated)
- book_id: UUID (references books.id, CASCADE DELETE)
- chapter_number: INTEGER
- title: VARCHAR(300)
- content: TEXT
- word_count: INTEGER
- estimated_reading_time_minutes: INTEGER
- vocabulary_words: JSONB (default '[]')
- created_at: TIMESTAMP (default NOW())
- UNIQUE(book_id, chapter_number)
```

### questions
```sql
- id: UUID (primary key, auto-generated)
- book_id: UUID (references books.id, CASCADE DELETE)
- chapter_id: UUID (references chapters.id, CASCADE DELETE)
- question_text: TEXT
- question_type: VARCHAR(50) (default 'comprehension')
- difficulty_level: VARCHAR(20) (default 'medium')
- expected_keywords: JSONB (default '[]')
- min_word_count: INTEGER (default 20)
- max_word_count: INTEGER (default 200)
- order_index: INTEGER
- is_active: BOOLEAN (default true)
- created_at: TIMESTAMP (default NOW())
```

## Usage

### Process a Local EPUB File

```bash
python cli.py process-file path/to/book.epub \
    --age-range "8-12" \
    --reading-level "intermediate" \
    --genre "adventure"
```

### Download from Project Gutenberg

```bash
# Alice's Adventures in Wonderland
python cli.py process-gutenberg 11115 \
    --age-range "8-12" \
    --reading-level "beginner"

# With custom settings
python cli.py process-gutenberg 1342 \
    --age-range "12-16" \
    --reading-level "advanced" \
    --max-words 2500 \
    --questions 5
```

### Batch Processing

```bash
python cli.py batch books.json
```

Example `books.json`:
```json
[
  {
    "gutenberg_id": 11115,
    "age_range": "8-12",
    "reading_level": "beginner",
    "genre": "fantasy"
  },
  {
    "gutenberg_id": 76,
    "age_range": "10-14",
    "reading_level": "intermediate",
    "genre": "adventure"
  }
]
```

### List Processed Books

```bash
python cli.py list-books
```

### Test Database Connection

```bash
python cli.py test-db
```

## CLI Options

### `process-file` Command
```
Arguments:
  filepath              Path to .epub file

Options:
  --age-range TEXT      Target age range (e.g., "8-12") [default: 8-12]
  --reading-level TEXT  Reading level: beginner/intermediate/advanced [default: intermediate]
  --genre TEXT          Book genre [default: fiction]
  --max-words INT       Max words per chapter [default: 1500]
  --questions INT       Questions per chapter [default: 3]
  --dry-run            Preview without inserting to database
```

### `process-gutenberg` Command
```
Arguments:
  gutenberg_id          Project Gutenberg book ID

Options:
  (same as process-file)
```

## Project Structure

```
epub-processing-pipeline/
├── src/
│   ├── __init__.py
│   ├── config.py              # Configuration and environment variables
│   ├── database.py            # PostgreSQL connection and queries
│   ├── epub_parser.py         # EPUB extraction logic
│   ├── text_cleaner.py        # Gutenberg boilerplate removal
│   ├── chapter_splitter.py    # Intelligent chapter splitting
│   ├── question_generator.py  # Ollama integration
│   └── models.py              # Data models (Book, Chapter, Question)
├── prompts/
│   └── question_generation.txt  # LLM prompt template
├── tests/
│   ├── test_epub_parser.py
│   ├── test_text_cleaner.py
│   └── test_question_generator.py
├── cli.py                     # Main CLI interface
├── requirements.txt
├── .env.example
└── README.md
```

## How It Works

### 1. EPUB Extraction (`epub_parser.py`)
- Uses `ebooklib` to parse EPUB structure
- Extracts metadata (title, author, language, publisher)
- Reads all XHTML content files in reading order
- Converts HTML to clean text using BeautifulSoup

### 2. Text Cleaning (`text_cleaner.py`)
- Detects and removes Project Gutenberg license boilerplate
- Identifies header/footer patterns:
  - "*** START OF THE PROJECT GUTENBERG EBOOK..."
  - "*** END OF THE PROJECT GUTENBERG EBOOK..."
  - License sections, donation info, etc.
- Normalizes whitespace and encoding
- Preserves chapter markers

### 3. Chapter Splitting (`chapter_splitter.py`)
- Detects chapter boundaries using patterns:
  - "CHAPTER I", "Chapter 1", "Chapter One"
  - "SECTION", "PART", etc.
- Calculates word count per chapter
- Splits long chapters if they exceed max words:
  - Finds paragraph or scene boundaries
  - Maintains narrative flow
  - Creates sub-chapters (e.g., "Chapter 1 - Part 1")
- Calculates reading time (200 WPM)

### 4. Question Generation (`question_generator.py`)
- Sends chapter text to Ollama with structured prompt
- Generates 3 open-ended questions per chapter
- Question types: Why, How, Inference, Analysis
- Extracts expected keywords for answer validation
- Sanitizes LLM output to prevent hallucinations
- Retries on failure with exponential backoff

### 5. Database Insertion (`database.py`)
- Uses `psycopg2` for PostgreSQL connection
- Transaction-based insertion (rollback on error)
- Inserts book → chapters → questions in order
- Checks for duplicates (by title + author)
- Returns inserted book ID and statistics

## Prompt Template

Located in `prompts/question_generation.txt`:

```
You are an expert educator creating comprehension questions for children.

Book: {title} by {author}
Chapter {chapter_number}: {chapter_title}
Reading Level: {reading_level}
Age Range: {age_range}

Chapter Text:
{chapter_text}

Generate exactly {num_questions} open-ended comprehension questions that:
1. Are NOT multiple choice or yes/no questions
2. Start with "Why" or "How" to encourage critical thinking
3. Require 20-100 word thoughtful answers
4. Test understanding beyond simple recall
5. Are appropriate for {age_range} year olds
6. Focus on themes, character motivation, or cause-effect

For each question, provide 3-5 expected keywords that would appear in a good answer.

Respond ONLY with valid JSON (no markdown):
{{
  "questions": [
    {{
      "text": "Why did the character...",
      "keywords": ["motivation", "decision", "consequence"],
      "difficulty": "medium"
    }}
  ]
}}
```

## Example Processing Output

```bash
$ python cli.py process-gutenberg 11115

🔍 Fetching metadata for Gutenberg ID 11115...
📚 Found: "Alice's Adventures in Wonderland" by Lewis Carroll

📥 Downloading EPUB...
✅ Downloaded 145KB

📖 Extracting text...
✅ Extracted 26,432 words from 12 sections

🧹 Cleaning text...
✅ Removed 2,847 words of boilerplate
✅ Cleaned text: 23,585 words

📑 Splitting chapters...
✅ Detected 12 natural chapters
✅ Split Chapter 7 into 2 sections (too long)
✅ Final: 13 chapters, avg 1,814 words each

🤖 Generating questions with Ollama...
✅ Chapter 1: 3 questions generated
✅ Chapter 2: 3 questions generated
...
✅ Chapter 13: 3 questions generated
✅ Total: 39 questions

💾 Inserting into database...
✅ Book inserted: 550e8400-e29b-41d4-a716-446655440000
✅ 13 chapters inserted
✅ 39 questions inserted

📊 Summary:
   Title: Alice's Adventures in Wonderland
   Author: Lewis Carroll
   Chapters: 13
   Questions: 39
   Total Words: 23,585
   Est. Reading Time: 118 minutes
   Database ID: 550e8400-e29b-41d4-a716-446655440000

✨ Processing complete!
```

## Troubleshooting

### Database Connection Error
```bash
# Test connection
python cli.py test-db

# Check PostgreSQL is running
pg_isready

# Verify credentials
psql $DATABASE_URL -c "SELECT version();"
```

### Ollama Not Running
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Pull model if not available
ollama pull llama3.2
```

### Question Generation Fails
- Try smaller model: `ollama pull phi3`
- Reduce chapter size: `--max-words 1000`
- Check Ollama logs for errors
- Increase timeout in `.env`: `OLLAMA_TIMEOUT=180`

### Duplicate Book Error
```sql
-- Check existing books
psql $DATABASE_URL -c "SELECT id, title, author FROM books;"

-- Delete if needed (cascades to chapters/questions)
psql $DATABASE_URL -c "DELETE FROM books WHERE id='<uuid>';"
```

## Popular Gutenberg Books for Testing

| ID | Title | Author | Recommended Age |
|----|-------|--------|-----------------|
| 11115 | Alice's Adventures in Wonderland | Lewis Carroll | 8-12 |
| 76 | The Adventures of Tom Sawyer | Mark Twain | 10-14 |
| 1661 | The Adventures of Sherlock Holmes | Arthur Conan Doyle | 12-16 |
| 1342 | Pride and Prejudice | Jane Austen | 14+ |
| 84 | Frankenstein | Mary Shelley | 14+ |

## Development

### Run Tests
```bash
pytest tests/ -v
```

### Add New Question Template
Edit `prompts/question_generation.txt` and adjust the prompt structure.

### Customize Chapter Splitting
Edit `src/chapter_splitter.py` - modify regex patterns or split logic.

## License

This tool processes public domain books from Project Gutenberg. Ensure compliance with Project Gutenberg's terms when distributing processed content.

## Support

For issues:
- Check existing GitHub issues
- Review Ollama docs: https://ollama.com/docs
- Project Gutenberg: https://www.gutenberg.org