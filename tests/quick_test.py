#!/usr/bin/env python3
"""
Quick test script: Download a Gutenberg book and process only first 2-3 chapters.
Perfect for testing the complete pipeline without processing an entire book.
"""

import sys
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import settings
from src.epub_parser import EPUBParser, download_gutenberg_epub
from src.content_analyzer import ContentAnalyzer
from src.chapter_splitter import ChapterSplitter, calculate_reading_time
from src.question_generator import QuestionGenerator
from src.database import DatabaseManager
from src.models import Book, Chapter, Question, ProcessedBook

console = Console()

# Configuration
GUTENBERG_ID = 11115  # Alice in Wonderland (you can change this)
MAX_CHAPTERS_TO_PROCESS = 2  # Only process first 2 chapters
AGE_RANGE = "8-12"
READING_LEVEL = "beginner"
GENRE = "fantasy"


def quick_test():
    """Quick test with limited chapters."""
    
    console.print("\n[bold blue]🚀 Quick Pipeline Test[/bold blue]")
    console.print(f"Processing first {MAX_CHAPTERS_TO_PROCESS} chapters only\n")
    
    try:
        # 1. Download EPUB
        console.print(f"[bold]📥 Downloading Gutenberg book {GUTENBERG_ID}...[/bold]")
        filepath = download_gutenberg_epub(GUTENBERG_ID, ".")
        console.print(f"[green]✓[/green] Downloaded to {filepath}\n")
        
        # 2. Parse EPUB
        console.print("[bold]📖 Extracting EPUB...[/bold]")
        parser = EPUBParser(filepath)
        epub_data = parser.parse()
        metadata = epub_data['metadata']
        raw_text = epub_data['raw_text']
        console.print(f"[green]✓[/green] Extracted {len(raw_text.split())} words\n")
        
        # 3. Analyze content
        console.print("[bold]🔍 Analyzing book structure with LLM...[/bold]")
        analyzer = ContentAnalyzer()
        analysis = analyzer.analyze_book_structure(raw_text)
        
        console.print(f"[green]✓[/green] Analysis complete:")
        console.print(f"   - Deleting {len(analysis['delete_pages'])} pages (Gutenberg boilerplate)")
        console.print(f"   - Found {len(analysis['metadata_pages'])} metadata pages\n")
        
        # 4. Extract clean content
        console.print("[bold]🧹 Extracting clean content...[/bold]")
        cleaned_text, metadata_sections = analyzer.apply_analysis(raw_text, analysis)
        console.print(f"[green]✓[/green] Extracted {len(cleaned_text.split())} words\n")
        
        # 5. Split chapters
        console.print("[bold]📑 Splitting chapters...[/bold]")
        splitter = ChapterSplitter(READING_LEVEL)
        content_chapters = splitter.split(cleaned_text)
        
        # LIMIT TO FIRST N CHAPTERS
        content_chapters = content_chapters[:MAX_CHAPTERS_TO_PROCESS]
        
        console.print(f"[green]✓[/green] Processing {len(content_chapters)} chapters (limited for testing)\n")
        
        # Add metadata sections
        all_chapters = []
        for meta in metadata_sections:
            if meta['page_range'][0] < analysis['content_start_page']:
                all_chapters.append({
                    'number': len(all_chapters) + 1,
                    'title': meta['title'],
                    'content': meta['content'],
                    'word_count': len(meta['content'].split()),
                    'is_metadata': True
                })
        
        for chapter in content_chapters:
            chapter['number'] = len(all_chapters) + 1
            chapter['is_metadata'] = False
            all_chapters.append(chapter)
        
        console.print(f"[dim]Total: {len(all_chapters)} chapters (including metadata)[/dim]\n")
        
        # 6. Generate questions
        console.print("[bold]🤖 Generating questions with Ollama...[/bold]")
        generator = QuestionGenerator()
        
        all_questions = []
        content_count = 0
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Generating questions...", total=len(content_chapters))
            
            for chapter_data in all_chapters:
                if chapter_data.get('is_metadata', False):
                    all_questions.append([])
                    continue
                
                questions_data = generator.generate_questions(
                    title=metadata['title'],
                    author=metadata['author'],
                    chapter_number=chapter_data['number'],
                    chapter_title=chapter_data['title'],
                    chapter_text=chapter_data['content'],
                    reading_level=READING_LEVEL,
                    age_range=AGE_RANGE,
                    num_questions=3
                )
                all_questions.append(questions_data)
                content_count += 1
                progress.update(task, advance=1)
        
        total_questions = sum(len(q) for q in all_questions)
        console.print(f"[green]✓[/green] Generated {total_questions} questions\n")
        
        # 7. Build data models
        console.print("[bold]📦 Building data models...[/bold]")
        
        # Extract description
        first_content = next((c['content'] for c in all_chapters if not c.get('is_metadata', False)), cleaned_text)
        paragraphs = [p.strip() for p in first_content.split('\n\n') if p.strip()]
        description = paragraphs[0][:500] if paragraphs else "Test book"
        
        book = Book(
            title=f"[TEST] {metadata['title']} (First {MAX_CHAPTERS_TO_PROCESS} Chapters)",
            author=metadata['author'],
            description=description,
            age_range=AGE_RANGE,
            reading_level=READING_LEVEL,
            genre=GENRE,
            total_chapters=len(all_chapters),
            estimated_reading_time_minutes=sum(
                calculate_reading_time(c['word_count']) for c in all_chapters
            ),
            isbn=metadata.get('isbn'),
            publication_year=metadata.get('publication_year')
        )
        
        chapters = []
        questions = []
        
        for i, chapter_data in enumerate(all_chapters):
            chapter = Chapter(
                book_id=book.id,
                chapter_number=chapter_data['number'],
                title=chapter_data['title'],
                content=chapter_data['content'],
                word_count=chapter_data['word_count'],
                estimated_reading_time_minutes=calculate_reading_time(chapter_data['word_count'])
            )
            chapters.append(chapter)
            
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
        
        # 8. Insert to database (using the complete pipeline method)
        console.print("[bold]💾 Inserting into database...[/bold]")
        
        processed_book = ProcessedBook(book=book, chapters=chapters, questions=questions)
        
        db = DatabaseManager()
        
        try:
            # Use the complete pipeline insertion method
            book_id, num_chapters, num_questions = db.insert_processed_book(processed_book)
            
            console.print(f"[green]✓[/green] Book inserted: {book_id}")
            console.print(f"[green]✓[/green] {num_chapters} chapters inserted")
            console.print(f"[green]✓[/green] {num_questions} questions inserted\n")
            
        except ValueError as e:
            # This handles duplicate detection
            console.print(f"[yellow]⚠[/yellow] {e}")
            if "[TEST]" in book.title and input("Delete existing test book and retry? (y/N): ").lower() == 'y':
                # Find and delete the existing test book
                existing_id = db.check_duplicate(book.title, book.author)
                if existing_id:
                    import psycopg2
                    conn = psycopg2.connect(db.database_url)
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM books WHERE id = %s", (existing_id,))
                    conn.commit()
                    conn.close()
                    console.print("[green]✓[/green] Deleted old test book, retrying...\n")
                    
                    # Retry insertion
                    book_id, num_chapters, num_questions = db.insert_processed_book(processed_book)
                    console.print(f"[green]✓[/green] Book inserted: {book_id}")
                    console.print(f"[green]✓[/green] {num_chapters} chapters inserted")
                    console.print(f"[green]✓[/green] {num_questions} questions inserted\n")
            else:
                console.print("[yellow]Skipped insertion.[/yellow]\n")
                return
        
        # Summary
        console.print("[bold green]✨ Quick test complete![/bold green]\n")
        console.print("📊 Summary:")
        console.print(f"   Title: {book.title}")
        console.print(f"   Chapters: {len(chapters)}")
        console.print(f"   Questions: {len(questions)}")
        console.print(f"   Database ID: {book_id}\n")
        
        console.print("🔍 Verify in database:")
        console.print(f"   [dim]SELECT * FROM books WHERE id='{book_id}';[/dim]")
        console.print(f"   [dim]SELECT * FROM chapters WHERE book_id='{book_id}';[/dim]")
        console.print(f"   [dim]SELECT * FROM questions WHERE book_id='{book_id}';[/dim]\n")
        
    except Exception as e:
        console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    console.print("\n[bold]Configuration:[/bold]")
    console.print(f"  Gutenberg ID: {GUTENBERG_ID}")
    console.print(f"  Max chapters: {MAX_CHAPTERS_TO_PROCESS}")
    console.print(f"  Age range: {AGE_RANGE}")
    console.print(f"  Reading level: {READING_LEVEL}\n")
    
    if input("Start quick test? (Y/n): ").lower() != 'n':
        quick_test()
    else:
        console.print("[yellow]Cancelled.[/yellow]\n")