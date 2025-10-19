# Database Migrations

This project uses SQL migration files to manage database schema changes.

## Migration Files

Migration files are numbered sequentially and stored in this directory:
- `001_add_draft_book.sql` - Initial draft system tables
- `002_add_tags_to_draft_book.sql` - Add tags column for AI categorization

## Running Migrations

### Option 1: Using the migration runner script (Recommended)

```bash
python run_migration.py migrations/002_add_tags_to_draft_book.sql
```

### Option 2: Using psql directly

```bash
psql $DATABASE_URL -f migrations/002_add_tags_to_draft_book.sql
```

### Option 3: Using the Python script directly

```python
from src.database import DatabaseManager
import psycopg2

with psycopg2.connect(DatabaseManager().get_database_url()) as conn:
    with conn.cursor() as cur:
        with open('migrations/002_add_tags_to_draft_book.sql', 'r') as f:
            cur.execute(f.read())
    conn.commit()
```

## Creating New Migrations

1. Create a new SQL file with the next sequential number:
   ```
   migrations/003_your_migration_name.sql
   ```

2. Add migration description and SQL commands:
   ```sql
   -- Migration: Brief description
   -- Description: Detailed description
   -- Created: YYYY-MM-DD
   
   -- Your SQL commands here
   ALTER TABLE ...
   ```

3. Run the migration using one of the methods above

## Checking Current Schema

To see the current draft_book table structure:

```sql
\d draft_book
```

Or programmatically:

```python
from src.database import DatabaseManager
db = DatabaseManager()
with db.get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'draft_book'
        """)
        for row in cur.fetchall():
            print(row)
```
