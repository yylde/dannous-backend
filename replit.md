# Kids Reading Platform - EPUB Processing Pipeline

## Overview
This project is an EPUB processing pipeline for a kids' reading platform. Its primary purpose is to download books from Project Gutenberg, process them into child-friendly formats, generate comprehension questions and vocabulary, and store them in a PostgreSQL database. The platform supports automatic content categorization with AI-extracted tags and provides grade-level reading benchmarks. It features a robust draft system for incremental book processing and a user-friendly admin UI for manual chapter splitting and content management.

## User Preferences
The user prefers:
- Manual control over chapter splitting instead of AI automation
- Visual feedback for word count validation
- Simple, intuitive UI for book processing

## System Architecture

### UI/UX Decisions
The platform features a responsive admin UI with a clean, modern interface. It utilizes an infinite vertical scroll for book text display, removing traditional pagination for a streamlined user experience. Key UI elements include a persistent sidebar for draft selection with real-time status badges, an information icon for reading benchmarks, and visual word count validation (red/green indicators). Book content preserves original EPUB HTML formatting, including headings, and integrates vocabulary tooltips using `<abbr>` tags. The configuration settings include an interactive tags section with visual status indicators (pending/generating/ready/error) that shows tag generation progress, editable tag chips for manual tag management, and a dedicated save button for tags and cover URL.

### Technical Implementations
The core application is a Flask web application (`app.py`) providing a REST API. It uses a Python-based EPUB parser (`src/epub_parser.py`) for extracting both plain text and HTML content. Question and vocabulary generation are handled by an Ollama LLM (`src/question_generator.py`) and executed asynchronously in the background using Python threading for each detected grade level. The system includes a comprehensive draft system that auto-saves progress and tracks chapter generation status. AI is used for automatic tag extraction (individual grade tags like "grade-3" and genre tags) at book download time, running asynchronously with status tracking (pending → generating → ready → error). Tags are saved and transferred upon book finalization. Database schema includes grade_level column in draft_questions table and tag_status column in draft_books table. **Model-agnostic design:** The LLM integration works with ANY Ollama model (thinking models like DeepSeek-R1 or standard models like Llama/Mistral) via intelligent retry strategies, automatic thinking-tag removal, and robust JSON extraction.

### Feature Specifications
- **Draft System:** Allows incremental processing, auto-saving, and async question generation with real-time status updates.
- **Chapter Management:** Manual chapter splitting via UI, with visual word count validation and editable chapter content.
- **AI-Powered Tagging:** Automatic extraction of individual grade-level tags (grade-1, grade-2, etc.) and genre tags at book download time. Tags are generated asynchronously and tracked with tag_status column.
- **Multi-Grade Question Generation:** Generates separate questions and vocabulary for EACH detected grade level. If a book is tagged for grades 2-4, it generates questions specifically for grade-2, grade-3, and grade-4 students.
- **Grade-Specific Vocabulary:** Generates 8 vocabulary words per grade level, with definitions and examples tailored to that grade's comprehension level. Each vocabulary item includes a grade_level field.
- **Automatic Question Regeneration:** Questions are automatically regenerated whenever tags are saved (manual edits) or regenerated (AI-powered). Smart regeneration only processes changed grades: deletes questions for removed grades, generates questions for added grades, and preserves questions for unchanged grades. Automatically handles edge cases like removing all grade tags.
- **Tag Regeneration:** AI-powered tag regeneration button that re-analyzes the book content and automatically triggers question regeneration when new tags are ready. Includes duplicate request protection to prevent concurrent tag generation jobs.
- **Vocabulary Tooltips:** Injected into HTML content for interactive definitions.
- **Book Cover URL:** Option to add a cover image URL to books.
- **Reading Benchmarks:** A modal displaying reading benchmarks (WPM, total words, pages) by grade level.

### System Design Choices
The architecture separates concerns into an EPUB parser, a question generator, and a database manager. Data persistence is managed by PostgreSQL. The system relies on `ON DELETE CASCADE` constraints in the database for data integrity during draft deletion. AI prompt engineering is used to ensure consistent output from the LLM, with robust parsing to handle flexible LLM responses.

## External Dependencies
- **PostgreSQL:** Primary database for storing book metadata, chapters, questions, and vocabulary.
- **Ollama:** Used as the Large Language Model (LLM) for generating comprehension questions, vocabulary, and AI-powered tags.
- **Project Gutenberg:** Source for downloading EPUB books.
- **Flask:** Python web framework for the backend application and API.