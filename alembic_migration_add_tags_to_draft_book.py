"""add_tags_to_draft_book

Revision ID: 3a7f8b9c2d1e
Revises: 2276cd65baaf
Create Date: 2025-10-19 01:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a7f8b9c2d1e'
down_revision: Union[str, Sequence[str], None] = '2276cd65baaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add tags column to draft_books table."""
    # Step 1: Add tags column to draft_books table (JSONB array)
    op.execute("""
        ALTER TABLE draft_books 
        ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]';
    """)
    
    # Step 2: Add GIN index for efficient tag filtering
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_draft_book_tags 
        ON draft_books USING GIN (tags);
    """)
    
    # Step 3: Add comment to document the column
    op.execute("""
        COMMENT ON COLUMN draft_books.tags IS 
        'AI-extracted tags for genre and grade-level categorization (e.g., ["adventure", "fantasy", "grades-4-6"])';
    """)


def downgrade() -> None:
    """Downgrade schema - Remove tags column from draft_books table."""
    # Step 1: Drop index
    op.execute("""
        DROP INDEX IF EXISTS idx_draft_book_tags;
    """)
    
    # Step 2: Drop tags column
    op.execute("""
        ALTER TABLE draft_books 
        DROP COLUMN IF EXISTS tags;
    """)
