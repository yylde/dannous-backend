# Kids Reading Platform - EPUB Processing Pipeline

## Overview
This project develops an EPUB processing pipeline for a kids' reading platform. It automates the download and transformation of books from Project Gutenberg into child-friendly formats, including the generation of comprehension questions and vocabulary, and stores them in a PostgreSQL database. The platform features AI-driven content categorization with grade-level benchmarks, a robust draft system for incremental processing, and an admin UI for content management and manual chapter splitting. The business vision is to create an engaging reading experience for children, leveraging AI to tailor content and support learning, with significant market potential in educational technology.

## User Preferences
The user prefers:
- Manual control over chapter splitting instead of AI automation
- Visual feedback for word count validation
- Simple, intuitive UI for book processing

## System Architecture

### UI/UX Decisions
The platform features a responsive admin UI designed for clarity and efficiency. Key UI elements include a persistent sidebar for draft selection with real-time status badges, an information icon for reading benchmarks, and visual word count validation (red/green indicators). A compact status widget in the header displays real-time Ollama queue information, with a dedicated queue monitoring page for comprehensive task visibility. The chapter editor and book text are presented in a side-by-side layout, allowing seamless manual copy-pasting of HTML content with automatic preservation of formatting and images (embedded as base64 data URIs). Text usage tracking visually highlights paragraphs already used in chapters with unique color coding. The configuration settings include interactive tag chips with status indicators and manual editing capabilities, along with a dedicated save button for tags and cover URL. The system supports multi-session workflows, automatically resuming progress when a draft is reloaded.

### Technical Implementations
The core is a Flask web application, structured using an application factory pattern with blueprints for modularity. It employs a Python-based EPUB parser for both text and HTML content, including image extraction. Question, vocabulary, and description generation are handled by an Ollama LLM and executed asynchronously using Python threading, with a robust draft system that auto-saves progress. AI-powered tag generation uses only book title and author for faster, asynchronous processing. Description generation is a two-step AI process: synopsis generation from initial book text followed by child-friendly description creation. The database schema includes fields for grade levels, tag status, AI-generated descriptions, and copy position markers. The contenteditable div for chapters syncs both plain text and HTML content. The LLM integration is model-agnostic, supporting various Ollama models with intelligent retry strategies and robust JSON extraction. GPU-optimized processing is controlled via the `PARALLEL_GENERATION` environment variable.

### Feature Specifications
- **Draft System:** Supports incremental processing, auto-saving, async question generation with real-time updates, and uniqueness enforcement by Gutenberg ID.
- **Queue Management:** Real-time monitoring and control of the Ollama AI queue via a header widget and a dedicated full-page monitor, including task type, priority, and status, with flush functionality.
- **Chapter Management:** Manual chapter splitting through the UI, with word count validation and fully editable HTML content.
- **AI-Powered Tagging:** Asynchronous generation of grade-level and genre tags from book title and author, with status tracking.
- **AI-Powered Description Generation:** Asynchronous, two-step generation of child-friendly book descriptions, with manual editing and regeneration options.
- **EPUB Image Extraction:** Automatic extraction and embedding of EPUB images as base64 data URIs in HTML content.
- **Text Usage Tracking:** Fuzzy matching to highlight used book paragraphs with chapter-specific color coding, refreshed automatically and manually.
- **Multi-Grade Question Generation:** Generates grade-specific questions and vocabulary for each detected grade level.
- **Grade-Specific Vocabulary:** Generates 8 vocabulary words per grade, with definitions and examples tailored to that grade.
- **Automatic Question Regeneration:** Smart regeneration of questions triggered by tag changes or manual edits, processing only affected grades.
- **Chapter-Level Question Regeneration:** Independent regeneration of questions for individual chapters.
- **Tag Regeneration:** AI-powered regeneration of tags, triggering question regeneration, with duplicate request protection.
- **Vocabulary Tooltips:** Interactive vocabulary definitions embedded in HTML.
- **Book Cover URL:** Option to add a cover image URL.
- **Reading Benchmarks:** Modal display of reading benchmarks by grade level.

### System Design Choices
The architecture emphasizes separation of concerns (EPUB parser, question generator, database manager). Data persistence is handled by PostgreSQL with `ON DELETE CASCADE` for integrity. AI prompt engineering and robust parsing ensure consistent LLM output. An Ollama priority queue system manages all LLM API calls with configurable worker threads, priority levels (tags, descriptions, questions), and graceful shutdown, ensuring efficient resource utilization and task ordering.

## External Dependencies
- **PostgreSQL:** Primary database for all project data.
- **Ollama:** Large Language Model (LLM) for content generation (questions, vocabulary, tags, descriptions).
- **Project Gutenberg:** Source for downloading EPUB books.
- **Flask:** Python web framework for the backend application and API.