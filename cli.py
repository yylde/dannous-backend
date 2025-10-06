#!/usr/bin/env python3
"""CLI for EPUB processing pipeline."""

import click
import logging
import sys
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import Optional

from src.config import settings
from src.epub_parser import EPUBParser, download_gutenberg_epub
from src.text_cleaner import TextCleaner, extract_description
from src.chapter_splitter import ChapterSplitter, calculate_reading_time
from src.question_generator import QuestionGenerator, save_prompt_template
from src.database import DatabaseManager
from src.models import Book, Chapter, Question, ProcessedBook

console = Console()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

if settings.log_file:
    file_handler = logging.FileHandler(settings.log_file)
    logging.getLogger().addHandler(file_handler)

logger = logging.getLogger(__name__)


@click.group()
def cli():
    """EPUB Processing Pipeline for Kids Reading Platform."""
    pass


@cli.command()
@click.argument('filepath', type=click.Path(exists=True))
@click.option('--age-range', default=None, help='Target age range (e.g., "8-12")')
@click.option('--reading-level', default=None, help='Reading level: beginner/intermediate/advanced')
@click.option('--genre', default=None, help='Book genre')
@click.option('--max-words', type=int, default=None, help='Max words per chapter')
@click.option('--questions', type=int, default=None, help='Questions per chapter')
@click.option('--dry-run', is_flag=True, help='Preview without inserting to database')
def process_file(
    filepath: str,
    age_range: Optional[str],
    reading_level: Optional[str],
    genre: Optional[str],
    max_words: Optional[int],
    questions: Optional[int],
    dry_run: bool
):
    """Process a local EPUB file."""
    age_range = age_range or settings.default_age_range
    reading_level = reading_level or settings.default_reading_level
    genre = genre or settings.default_genre
    
    console.print(f"\n[bold blue]📚 Processing EPUB File[/bold blue]")
    console.print(f"File: {filepath}")
    console.print(f"Age Range: {age_range}")
    console.print(f"Reading Level: {reading_level}\n")
    
    try:
        processed_book = _process_epub(
            filepath, age_range, reading_level, genre, max_words, questions
        )
        
        if dry_run:
            console.print("\n[yellow]🔍 DRY RUN - Not inserting to database[/yellow]")
            _print_summary(processed_book.get_statistics())
        else:
            _insert_to_database(processed_book)
        
        console.print("\n[bold green]✨ Processing complete![/bold green]\n")
        
    except Exception as e:
        console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
        logger.exception("Processing failed")
        sys.exit(1)


@cli.command()
@click.argument('gutenberg_id', type=int)
@click.option('--age-range', default=None, help='Target age range (e.g., "8-12")')
@click.option('--reading-level', default=None, help='Reading level: beginner/intermediate/advanced')
@click.option('--genre', default=None, help='Book genre')
@click.option('--max-words', type=int, default=None, help='Max words per chapter')
@click.option('--questions', type=int, default=None, help='Questions per chapter')
@click.option('--dry-run', is_flag=True, help='Preview without inserting to database')
def process_gutenberg(
    gutenberg_id: int,
    age_range: Optional[str],
    reading_level: Optional[str],
    genre: Optional[str],
    max_words: Optional[int],
    questions: Optional[int],
    dry_run: bool
):
    """Download and process a book from Project Gutenberg."""
    age_range = age_range or settings.default_age_range
    reading_level = reading_level or settings.default_reading_level
    genre = genre or settings.default_genre
    
    console.print(f"\n[bold blue]📥 Downloading from Project Gutenberg[/bold blue]")
    console.print(f"Gutenberg ID: {gutenberg_id}\n")
    
    try:
        # Download EPUB
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="Downloading EPUB...", total=None)
            filepath = download_gutenberg_epub(gutenberg_id, ".")
        
        console.print(f"[green]✓[/green] Downloaded to {filepath}\n")
        
        # Process it
        processed_book = _process_epub(
            filepath, age_range, reading_level, genre, max_words, questions
        )
        
        if dry_run:
            console.print("\n[yellow]🔍 DRY RUN - Not inserting to database[/yellow]")
            _print_summary(processed_book.get_statistics())
        else:
            _insert_to_database(processed_book)
        
        console.print("\n[bold green]✨ Processing complete![/bold green]\n")
        
    except Exception as e:
        console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
        logger.exception("Processing failed")
        sys.exit(1)


@cli.command()
@click.argument('config_file', type=click.Path(exists=True))
def batch(config_file: str):
    """Batch process multiple books from a JSON config file."""
    console.print(f"\n[bold blue]📚 Batch Processing[/bold blue]")
    console.print(f"Config: {config_file}\n")
    
    try:
        with open(config_file) as f:
            books = json.load(f)
        
        total = len(books)
        console.print(f"Processing {total} books...\n")
        
        results = []
        for i, book_config in enumerate(books, 1):
            console.print(f"\n[bold]Book {i}/{total}[/bold]")
            
            try:
                gutenberg_id = book_config.get('gutenberg_id')
                filepath = book_config.get('filepath')
                
                if gutenberg_id:
                    filepath = download_gutenberg_epub(gutenberg_id, ".")
                elif not filepath:
                    raise ValueError("Must provide either gutenberg_id or filepath")
                
                processed_book = _process_epub(
                    filepath,
                    book_config.get('age_range', settings.default_age_range),
                    book_config.get('reading_level', settings.default_reading_level),
                    book_config.get('genre', settings.default_genre),
                    book_config.get('max_words'),
                    book_config.get('questions')
                )
                
                _insert_to_database(processed_book)
                results.append({'success': True, 'book': processed_book.book.title})
                
            except Exception as e:
                console.print(f"[red]Failed: {e}[/red]")
                results.append({'success': False, 'error': str(e)})
        
        # Summary
        success_count = sum(1 for r in results if r['success'])
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"✓ Successful: {success_count}/{total}")
        console.print(f"✗ Failed: {total - success_count}/{total}\n")
        
    except Exception as e:
        console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
        sys.exit(1)


@cli.command()
def list_books():
    """List all books in the database."""
    console.print("\n[bold blue]📚 Books in Database[/bold blue]\n")
    
    try:
        db = DatabaseManager()
        books = db.list_books()
        
        if not books:
            console.print("[yellow]No books found in database.[/yellow]\n")
            return
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Title", style="cyan", width=40)
        table.add_column("Author", style="green", width=25)
        table.add_column("Chapters", justify="right")
        table.add_column("Age Range", justify="center")
        table.add_column("Level", justify="center")
        table.add_column("Created", style="dim")
        
        for book in books:
            table.add_row(
                book['title'][:40],
                book['author'][:25],
                str(book['total_chapters']),
                book['age_range'],
                book['reading_level'],
                book['created_at'].strftime('%Y-%m-%d') if book['created_at'] else 'N/A'
            )
        
        console.print(table)
        console.print(f"\n[dim]Total: {len(books)} books[/dim]\n")
        
    except Exception as e:
        console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
        sys.exit(1)


@cli.command()
def test_db():
    """Test database connection."""
    console.print("\n[bold blue]🔌 Testing Database Connection[/bold blue]\n")
    
    try:
        db = DatabaseManager()
        if db.test_connection():
            console.print("[green]✓ Database connection successful![/green]\n")
        else:
            console.print("[red]✗ Database connection failed![/red]\n")
            sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]\n")
        sys.exit(1)


@cli.command()
def save_prompts():
    """Save prompt templates to prompts/ directory."""
    console.print("\n[bold blue]💾 Saving Prompt Templates[/bold blue]\n")
    
    try:
        save_prompt_template()
        console.print("[green]✓ Saved to prompts/question_generation.txt[/green]\n")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]\n")
        sys.exit(1)


def _process_epub(
    filepath: str,
    age_range: str,
    reading_level: str,
    genre: str,
    max_words: Optional[int],
    num_questions: Optional[int]
) -> ProcessedBook:
    """Process an EPUB file through the complete pipeline."""
    
    # 1. Parse EPUB
    console.print("[bold]📖 Extracting EPUB...[/bold]")
    parser = EPUBParser(filepath)
    epub_data = parser.parse()
    metadata = epub_data['metadata']
    raw_text = epub_data['raw_text']
    console.print(f"[green]✓[/green] Extracted {len(raw_text.split())} words\n")
    
    # 2. Clean text
    console.print("[bold]🧹 Cleaning text...[/bold]")
    cleaner = TextCleaner()
    cleaned_text = cleaner.clean(raw_text)
    orig, cleaned, removed = cleaner.get_cleaning_stats()
    console.print(f"[green]✓[/green] Removed {removed} words of boilerplate\n")
    
    # 3. Split chapters
    console.print("[bold]📑 Splitting chapters...[/bold]")
    splitter = ChapterSplitter(reading_level)
    if max_words:
        splitter.max_words = max_words
    chapters_data = splitter.split(cleaned_text)
    console.print(f"[green]✓[/green] Created {len(chapters_data)} chapters\n")
    
    # 4. Generate questions
    console.print("[bold]🤖 Generating questions with Ollama...[/bold]")
    generator = QuestionGenerator()
    
    all_questions = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Generating questions...", total=len(chapters_data))
        
        for chapter_data in chapters_data:
            questions_data = generator.generate_questions(
                title=metadata['title'],
                author=metadata['author'],
                chapter_number=chapter_data['number'],
                chapter_title=chapter_data['title'],
                chapter_text=chapter_data['content'],
                reading_level=reading_level,
                age_range=age_range,
                num_questions=num_questions
            )
            all_questions.append(questions_data)
            progress.update(task, advance=1)
    
    total_questions = sum(len(q) for q in all_questions)
    console.print(f"[green]✓[/green] Generated {total_questions} questions\n")
    
    # 5. Build data models
    console.print("[bold]📦 Building data models...[/bold]")
    
    # Create book
    book = Book(
        title=metadata['title'],
        author=metadata['author'],
        description=extract_description(cleaned_text),
        age_range=age_range,
        reading_level=reading_level,
        genre=genre,
        total_chapters=len(chapters_data),
        estimated_reading_time_minutes=sum(
            calculate_reading_time(c['word_count']) for c in chapters_data
        ),
        isbn=metadata.get('isbn'),
        publication_year=metadata.get('publication_year')
    )
    
    # Create chapters
    chapters = []
    questions = []
    
    for i, chapter_data in enumerate(chapters_data):
        chapter = Chapter(
            book_id=book.id,
            chapter_number=chapter_data['number'],
            title=chapter_data['title'],
            content=chapter_data['content'],
            word_count=chapter_data['word_count'],
            estimated_reading_time_minutes=calculate_reading_time(chapter_data['word_count'])
        )
        chapters.append(chapter)
        
        # Create questions for this chapter
        for j, q_data in enumerate(all_questions[i]):
            question = Question(
                book_id=book.id,
                chapter_id=chapter.id,
                question_text=q_data['text'],
                question_type='comprehension',
                difficulty_level=q_data.get('difficulty', 'medium'),
                expected_keywords=q_data.get('keywords', []),
                min_word_count=settings.min_answer_words,
                max_word_count=settings.max_answer_words,
                order_index=j + 1
            )
            questions.append(question)
    
    console.print(f"[green]✓[/green] Created {len(chapters)} chapters, {len(questions)} questions\n")
    
    return ProcessedBook(book=book, chapters=chapters, questions=questions)


def _insert_to_database(processed_book: ProcessedBook):
    """Insert processed book into database."""
    console.print("[bold]💾 Inserting into database...[/bold]")
    
    try:
        db = DatabaseManager()
        book_id, num_chapters, num_questions = db.insert_processed_book(processed_book)
        
        console.print(f"[green]✓[/green] Book inserted: {book_id}")
        console.print(f"[green]✓[/green] {num_chapters} chapters inserted")
        console.print(f"[green]✓[/green] {num_questions} questions inserted\n")
        
        _print_summary(processed_book.get_statistics())
        
    except ValueError as e:
        console.print(f"[yellow]⚠ {e}[/yellow]")
        console.print("[yellow]Skipping insertion (book already exists)[/yellow]\n")
    except Exception as e:
        raise


def _print_summary(stats: dict):
    """Print processing summary."""
    console.print("\n[bold]📊 Summary:[/bold]")
    console.print(f"   Title: [cyan]{stats['title']}[/cyan]")
    console.print(f"   Author: [green]{stats['author']}[/green]")
    console.print(f"   Chapters: {stats['total_chapters']}")
    console.print(f"   Questions: {stats['total_questions']}")
    console.print(f"   Total Words: {stats['total_words']:,}")
    console.print(f"   Est. Reading Time: {stats['estimated_reading_time_minutes']} minutes")
    console.print(f"   Database ID: [dim]{stats['book_id']}[/dim]")


if __name__ == '__main__':
    cli()