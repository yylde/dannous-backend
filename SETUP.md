# Setup Guide - EPUB Processing Pipeline

Complete setup instructions for the EPUB processing pipeline.

## Prerequisites Checklist

- [ ] Python 3.9 or higher installed
- [ ] PostgreSQL database (from main reading platform) accessible
- [ ] Ollama installed and running
- [ ] Internet connection (for downloading books)

## Step-by-Step Setup

### 1. Install Python Dependencies

```bash
# Navigate to project directory
cd epub-processing-pipeline

# Install dependencies
pip install -r requirements.txt

# Verify installation
python -c "import ebooklib, psycopg2, ollama; print('All packages installed!')"
```

### 2. Install and Configure Ollama

**Install Ollama:**

```bash
# Linux/macOS
curl -fsSL https://ollama.com/install.sh | sh

# Windows
# Download from https://ollama.com/download
```

**Start Ollama:**

```bash
# Start the Ollama service (runs in background)
ollama serve
```

**Pull the LLM model:**

```bash
# Recommended: Llama 3.2 (3B parameters, fast)
ollama pull llama3.2

# Alternative models:
# ollama pull mistral      # 7B parameters, higher quality
# ollama pull phi3         # 3.8B parameters, Microsoft
# ollama pull gemma2:2b    # 2B parameters, very fast
```

**Verify Ollama is running:**

```bash
curl http://localhost:11434/api/tags
# Should return JSON with list of installed models
```

### 3. Configure Environment Variables

**Copy the example environment file:**

```bash
cp .env.example .env
```

**Edit `.env` with your settings:**

```bash
nano .env
```

**Required settings:**

```env
# Database (use same credentials as main reading platform)
DATABASE_URL=postgresql://username:password@localhost:5432/reading_platform

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Processing defaults
DEFAULT_AGE_RANGE=8-12
DEFAULT_READING_LEVEL=intermediate
```

### 4. Test Database Connection

```bash
python cli.py test-db
```

Expected output:
```
🔌 Testing Database Connection

✓ Database connection successful!
```

If this fails:
- Verify DATABASE_URL is correct
- Check PostgreSQL is running: `pg_isready`
- Test manually: `psql $DATABASE_URL -c "SELECT 1;"`

### 5. Verify Complete Setup

Run this verification script:

```bash
# Test all components
python -c "
from src.database import DatabaseManager
from src.epub_parser import EPUBParser
from src.question_generator import QuestionGenerator

print('Testing database...')
db = DatabaseManager()
assert db.test_connection(), 'Database failed'
print('✓ Database OK')

print('Testing Ollama...')
gen = QuestionGenerator()
print('✓ Ollama OK')

print('\n✅ All systems ready!')
"
```

## Quick Start Examples

### Example 1: Process Alice in Wonderland

```bash
python cli.py process-gutenberg 11115 \
    --age-range "8-12" \
    --reading-level "beginner"
```

### Example 2: Process a Local File

```bash
python cli.py process-file my-book.epub \
    --age-range "10-14" \
    --reading-level "intermediate" \
    --genre "adventure"
```

### Example 3: Batch Processing

```bash
python cli.py batch examples/batch_books.json
```

### Example 4: Dry Run (Preview Only)

```bash
python cli.py process-gutenberg 76 --dry-run
```

## Directory Structure

After setup, your project should look like this:

```
epub-processing-pipeline/
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── epub_parser.py
│   ├── text_cleaner.py
│   ├── chapter_splitter.py
│   ├── question_generator.py
│   └── models.py
├── prompts/
│   └── question_generation.txt
├── tests/
│   └── test_pipeline.py
├── examples/
│   └── batch_books.json
├── cli.py
├── requirements.txt
├── .env
├── .env.example
├── README.md
└── SETUP.md
```

## Common Issues and Solutions

### Issue: "ModuleNotFoundError: No module named 'src'"

**Solution:**
```bash
# Make sure you're in the project root
pwd

# Install in development mode
pip install -e .
```

### Issue: "Connection refused" to Ollama

**Solution:**
```bash
# Check if Ollama is running
ps aux | grep ollama

# Start Ollama if not running
ollama serve

# Check the port
netstat -an | grep 11434
```

### Issue: "Model not found" error

**Solution:**
```bash
# List installed models
ollama list

# Pull the required model
ollama pull llama3.2
```

### Issue: Questions are low quality

**Solutions:**
1. Try a larger model: `ollama pull mistral`
2. Update .env: `OLLAMA_MODEL=mistral`
3. Reduce chapter size: `--max-words 1000`
4. Check prompt template in `prompts/question_generation.txt`

### Issue: Database "book already exists" error

**Solution:**
```bash
# List existing books
python cli.py list-books

# Remove duplicate if needed (CAREFUL - cascades to chapters/questions)
psql $DATABASE_URL -c "DELETE FROM books WHERE id='<uuid>';"
```

### Issue: Out of memory when processing large books

**Solutions:**
1. Use smaller Ollama model: `ollama pull gemma2:2b`
2. Split into smaller chapters: `--max-words 800`
3. Process chapters individually (modify code)

## Performance Tuning

### For Faster Processing:

```env
# Use smaller, faster model
OLLAMA_MODEL=gemma2:2b

# Reduce questions per chapter
QUESTIONS_PER_CHAPTER=2

# Increase max chapter words (fewer chapters = fewer API calls)
MAX_CHAPTER_WORDS_INTERMEDIATE=2000
```

### For Higher Quality:

```env
# Use larger model
OLLAMA_MODEL=mistral

# More questions per chapter
QUESTIONS_PER_CHAPTER=5

# Smaller chapters (more focused questions)
MAX_CHAPTER_WORDS_INTERMEDIATE=1000
```

## Testing Your Setup

Run the test suite:

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

## Next Steps

1. **Save prompt template:**
   ```bash
   python cli.py save-prompts
   ```

2. **Process your first book:**
   ```bash
   python cli.py process-gutenberg 11115
   ```

3. **Verify in database:**
   ```bash
   python cli.py list-books
   ```

4. **Check the data:**
   ```bash
   # Connect to database
   psql $DATABASE_URL
   
   # Query the book
   SELECT id, title, author, total_chapters FROM books ORDER BY created_at DESC LIMIT 1;
   
   # Check chapters
   SELECT chapter_number, title, word_count FROM chapters WHERE book_id='<book-id>' ORDER BY chapter_number;
   
   # Check questions
   SELECT chapter_id, question_text FROM questions WHERE book_id='<book-id>' LIMIT 5;
   ```

## Advanced Configuration

### Custom Reading Levels

Edit `.env` to customize word limits per reading level:

```env
MAX_CHAPTER_WORDS_BEGINNER=600      # Younger readers (6-8)
MAX_CHAPTER_WORDS_INTERMEDIATE=1200 # Middle readers (8-12)
MAX_CHAPTER_WORDS_ADVANCED=2000     # Advanced readers (12+)
MIN_CHAPTER_WORDS=150               # Minimum viable chapter
```

### Custom Question Templates

Edit `prompts/question_generation.txt` to customize question generation:

- Modify question types (add inference, analysis, etc.)
- Change difficulty criteria
- Adjust keyword extraction logic
- Modify age-appropriateness guidelines

After editing, test with:
```bash
python cli.py process-gutenberg 76 --questions 1 --dry-run
```

### Database Connection Pooling

For batch processing, you may want connection pooling:

```python
# In src/database.py, add:
from psycopg2 import pool

class DatabaseManager:
    connection_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        dsn=database_url
    )
```

## Monitoring and Logging

### Enable Detailed Logging

```env
LOG_LEVEL=DEBUG
LOG_FILE=processing.log
```

### View Logs

```bash
# Follow log file
tail -f processing.log

# Search for errors
grep ERROR processing.log

# Check Ollama API calls
grep "Ollama" processing.log
```

## Production Deployment

### Using Docker (Optional)

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "cli.py"]
```

Build and run:

```bash
docker build -t epub-processor .
docker run --env-file .env epub-processor process-gutenberg 11115
```

### Automated Processing

Create a cron job for regular book imports:

```bash
# Edit crontab
crontab -e

# Add entry (process books daily at 2 AM)
0 2 * * * cd /path/to/epub-processing-pipeline && /usr/bin/python3 cli.py batch books_queue.json >> /var/log/epub-processor.log 2>&1
```

### CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Process Books
on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly
  workflow_dispatch:

jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python cli.py batch books.json
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

## Backup and Recovery

### Backup Books

```bash
# Export processed books
pg_dump $DATABASE_URL -t books -t chapters -t questions > books_backup.sql

# Restore
psql $DATABASE_URL < books_backup.sql
```

### Export Book Data as JSON

```python
# Create export script
from src.database import DatabaseManager
import json

db = DatabaseManager()
books = db.list_books()

with open('books_export.json', 'w') as f:
    json.dump(books, f, indent=2, default=str)
```

## Troubleshooting Checklist

When something goes wrong:

- [ ] Check Ollama is running: `curl http://localhost:11434/api/tags`
- [ ] Verify database connection: `python cli.py test-db`
- [ ] Check model is downloaded: `ollama list`
- [ ] Review logs: `cat processing.log`
- [ ] Test with dry-run first: `--dry-run`
- [ ] Verify .env file exists and has correct values
- [ ] Check Python version: `python --version` (3.9+)
- [ ] Ensure PostgreSQL is running: `pg_isready`

## Getting Help

1. **Check logs first:**
   ```bash
   tail -n 50 processing.log
   ```

2. **Enable debug mode:**
   ```bash
   LOG_LEVEL=DEBUG python cli.py process-gutenberg 11115
   ```

3. **Test individual components:**
   ```bash
   python -c "from src.text_cleaner import TextCleaner; print('OK')"
   python -c "from src.database import DatabaseManager; db=DatabaseManager(); db.test_connection()"
   ```

4. **Check GitHub issues** for common problems

5. **Review the main README.md** for usage examples

## Maintenance

### Regular Tasks

**Weekly:**
- Review processed books: `python cli.py list-books`
- Check log file size: `du -h processing.log`
- Update Ollama models: `ollama pull llama3.2`

**Monthly:**
- Update dependencies: `pip install -r requirements.txt --upgrade`
- Clean up old EPUB files: `rm gutenberg_*.epub`
- Vacuum database: `psql $DATABASE_URL -c "VACUUM ANALYZE;"`

**As Needed:**
- Update prompt templates based on question quality
- Adjust reading level configurations
- Fine-tune chapter splitting parameters

## Support and Contributing

For issues, questions, or contributions:

- Open an issue on GitHub
- Review existing documentation
- Check Ollama docs: https://ollama.com/docs
- PostgreSQL docs: https://www.postgresql.org/docs/

---

**You're all set!** 🎉

Try processing your first book:
```bash
python cli.py process-gutenberg 11115 --age-range "8-12" --reading-level "beginner"
```