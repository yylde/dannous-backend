#!/usr/bin/env python3
"""
Simple migration runner for SQL migration files.
Usage: python run_migration.py migrations/002_add_tags_to_book_drafts.sql
"""
import sys
import psycopg2
from src.config import settings

def run_migration(migration_file):
    """Run a SQL migration file."""
    print(f"Running migration: {migration_file}")
    
    try:
        # Read migration file
        with open(migration_file, 'r') as f:
            sql = f.read()
        
        # Connect to database
        conn = psycopg2.connect(settings.database_url)
        conn.autocommit = False
        
        try:
            with conn.cursor() as cur:
                # Execute migration
                cur.execute(sql)
                conn.commit()
                print(f"✓ Migration completed successfully: {migration_file}")
        except Exception as e:
            conn.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()
            
    except FileNotFoundError:
        print(f"✗ Migration file not found: {migration_file}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_migration.py <migration_file>")
        print("Example: python run_migration.py migrations/002_add_tags_to_book_drafts.sql")
        sys.exit(1)
    
    migration_file = sys.argv[1]
    run_migration(migration_file)
