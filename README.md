# Kids Reading Platform - EPUB Processing Pipeline

A web-based tool for downloading books from Project Gutenberg, splitting them into chapters, and generating comprehension questions for kids using AI.

## Features

- 📚 **Download books** from Project Gutenberg by ID
- 📄 **Infinite scroll** book view with preserved EPUB formatting and prominent headers
- ✂️ **Manual chapter splitting** with automatic text selection
- 📊 **Word count validation** based on difficulty levels (Beginner/Intermediate/Advanced)
- 🤖 **AI-powered question generation** using Ollama LLM
- 💾 **PostgreSQL database** for storing books, chapters, and questions
- 🎨 **Clean, responsive web UI** for easy book processing

## Prerequisites

Before setting up the project locally, ensure you have the following installed:

- **Python 3.11** or higher
- **PostgreSQL** (version 12 or higher)
- **Ollama** (for AI question generation)
  - Install from [ollama.ai](https://ollama.ai)
  - Pull the llama3.2 model: `ollama pull llama3.2`

## Local Setup Instructions

### 1. Clone the Repository

```bash
git clone <repository-url>
cd <project-directory>
```

### 2. Set Up Python Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up PostgreSQL Database

Create a new PostgreSQL database:

```bash
# Log into PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE kids_reading_db;

# Exit psql
\q
```

Run the schema setup:

```bash
psql -U postgres -d kids_reading_db -f schema.sql
```

### 5. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Database Configuration
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/kids_reading_db
PGHOST=localhost
PGPORT=5432
PGUSER=postgres
PGPASSWORD=your_password
PGDATABASE=kids_reading_db

# Ollama Configuration (optional, defaults shown)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

**Important:** Replace `your_password` with your PostgreSQL password.

### 6. Verify Ollama is Running

Make sure Ollama is running in the background:

```bash
# Check if Ollama is running
ollama list

# If not running, start it
ollama serve

# Pull the model (if not already installed)
ollama pull llama3.2
```

### 7. Run the Application

```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Usage

### Web Interface (Recommended)

1. Open your browser to `http://localhost:5000`
2. Enter a Project Gutenberg book ID (e.g., `11115` for Alice in Wonderland)
3. Click **Download Book**
4. Configure settings:
   - Age Range (e.g., 8-12)
   - Reading Level (Beginner/Intermediate/Advanced)
   - Genre
5. **Scroll through the book** - headers and chapter titles are highlighted in purple
6. **Select text** with your mouse to automatically add it to your chapter (no button needed!)
7. Enter a chapter title
8. Monitor the word count (green = valid range, red = out of range)
9. Click **Finish Chapter** when complete
10. Repeat for all chapters
11. Click **Save Book & Generate Questions** to process everything

### Difficulty Level Ranges

- **Beginner**: 300-800 words per chapter
- **Intermediate**: 800-1,500 words per chapter
- **Advanced**: 1,500-2,500 words per chapter

### Command Line Interface (Legacy)

```bash
# Process a book from Gutenberg
python cli.py process-gutenberg 11115 --age-range "8-12" --reading-level "beginner"

# Test database connection
python cli.py test-db

# List books
python cli.py list-books
```

## Project Structure

```
.
├── app.py                     # Flask web application
├── cli.py                     # Command-line interface (legacy)
├── requirements.txt           # Python dependencies
├── schema.sql                 # Database schema
├── src/
│   ├── epub_parser.py         # EPUB download and parsing
│   ├── question_generator.py  # AI question generation
│   ├── database.py            # Database operations
│   ├── models.py              # Data models
│   └── config.py              # Configuration
├── templates/
│   └── index.html             # Admin UI template
├── static/
│   ├── css/style.css          # Styling
│   └── js/app.js              # Frontend logic
└── downloads/                 # Downloaded EPUB files (auto-created)
```

## Database Schema

### Tables

- **books** - Book metadata (title, author, age range, reading level, genre)
  - CASCADE DELETE to chapters and questions
- **chapters** - Chapter content and metadata (linked to books)
  - CASCADE DELETE to questions
- **questions** - Comprehension questions with expected keywords (linked to chapters)

All tables have CASCADE delete for data integrity.

## How It Works

### 1. EPUB Download & Parsing
- Downloads EPUB from Project Gutenberg by ID
- Extracts metadata (title, author)
- Parses HTML content preserving headings (h1-h6) and paragraph structure
- Cleans and formats text for display

### 2. Manual Chapter Building (Web UI)
- Display book in infinite scroll view
- Headers/chapter titles styled prominently (purple, bold, larger font)
- User selects text → automatically added to current chapter
- Real-time word count validation with color indicators
- Visual highlighting shows what text has been added

### 3. AI Question Generation
- Uses Ollama LLM (llama3.2) to generate comprehension questions
- 3 open-ended questions per chapter
- Extracts expected keywords for answer validation
- Adjusts difficulty based on reading level

### 4. Database Storage
- Stores book metadata, chapters, and questions
- Transaction-based insertion with rollback on error
- Automatic reading time estimation (200 WPM)

## Troubleshooting

### Database Connection Issues

If you get database connection errors:

1. Check PostgreSQL is running: `pg_ctl status`
2. Verify your `.env` file has correct credentials
3. Test connection: `python cli.py test-db`

### Ollama Not Working

If question generation fails:

1. Check Ollama is running: `ollama list`
2. Verify model is installed: `ollama pull llama3.2`
3. Check the `OLLAMA_BASE_URL` in `.env` points to `http://localhost:11434`

### Port 5000 Already in Use

If port 5000 is occupied:

```bash
# Change port in app.py (last line)
app.run(host='0.0.0.0', port=5001, debug=True)
```

### Text Not Displaying Properly

If EPUB formatting looks wrong:
1. Check browser console for JavaScript errors
2. Verify the book downloaded successfully (check `downloads/` folder)
3. Try a different Gutenberg book ID

## Popular Gutenberg Books for Testing

| ID | Title | Author | Recommended Age |
|----|-------|--------|-----------------|
| 11115 | Alice's Adventures in Wonderland | Lewis Carroll | 8-12 |
| 76 | The Adventures of Tom Sawyer | Mark Twain | 10-14 |
| 1661 | The Adventures of Sherlock Holmes | Arthur Conan Doyle | 12-16 |
| 1342 | Pride and Prejudice | Jane Austen | 14+ |
| 84 | Frankenstein | Mary Shelley | 14+ |

## Development

### Running Tests

```bash
pytest
pytest --cov  # with coverage
```

### Adding New Features

1. Update database schema in `schema.sql`
2. Update models in `src/models.py`
3. Update database operations in `src/database.py`
4. Update Flask routes in `app.py`
5. Update UI in `templates/index.html` and `static/`

## Key Features Explained

### Automatic Text Selection
- Just select text in the book view with your mouse
- Text is automatically added to the current chapter (10+ characters)
- No "Add Text" button needed - streamlined workflow

### Prominent Headers
- Chapter titles and headers from the EPUB are preserved
- Styled with larger font, purple color, and bold weight
- H1/H2 headers have underline borders
- Clear visual hierarchy for easy navigation

### Infinite Scroll
- All book content in one scrollable view
- No page-by-page navigation needed
- Smooth reading experience

## License

This project is for educational purposes.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
