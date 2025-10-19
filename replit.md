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
The platform features a responsive admin UI with a clean, modern interface. It utilizes an infinite vertical scroll for book text display, removing traditional pagination for a streamlined user experience. Key UI elements include a persistent sidebar for draft selection with real-time status badges, an information icon for reading benchmarks, and visual word count validation (red/green indicators). Book content preserves original EPUB HTML formatting, including headings, and integrates vocabulary tooltips using `<abbr>` tags.

### Technical Implementations
The core application is a Flask web application (`app.py`) providing a REST API. It uses a Python-based EPUB parser (`src/epub_parser.py`) for extracting both plain text and HTML content. Question and vocabulary generation are handled by an Ollama LLM (`src/question_generator.py`) and executed asynchronously in the background using Python threading. The system includes a comprehensive draft system that auto-saves progress and tracks chapter generation status. AI is used for automatic tag extraction (genre, grade-appropriate) which are saved and transferred upon book finalization.

### Feature Specifications
- **Draft System:** Allows incremental processing, auto-saving, and async question generation with real-time status updates.
- **Chapter Management:** Manual chapter splitting via UI, with visual word count validation and editable chapter content.
- **AI-Powered Tagging:** Automatic extraction of genre and grade-level tags from book content.
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