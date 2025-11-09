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
The platform features a responsive admin UI with a clean, modern interface. **Side-by-side layout:** The chapter editor and book text are displayed side-by-side (50/50 split) to eliminate scrolling between sections - users can copy from the right panel and paste into the left panel seamlessly. Both panels are independently scrollable with a fixed 700px height. On smaller screens (<1024px), the layout automatically stacks vertically. Key UI elements include a persistent sidebar for draft selection with real-time status badges, an information icon for reading benchmarks, and visual word count validation (red/green indicators). Book content preserves original EPUB HTML formatting, including headings and images (embedded as base64 data URIs), and integrates vocabulary tooltips using `<abbr>` tags. The configuration settings include an interactive tags section with visual status indicators (pending/generating/ready/error) that shows tag generation progress, editable tag chips for manual tag management, and a dedicated save button for tags and cover URL. **Manual copy/paste workflow:** Users manually select and copy text from the book display (right panel), then paste into the chapter editor (left panel). HTML formatting (including images) is automatically preserved during paste operations via a custom paste event handler. **Text usage tracking:** A "🔄 Refresh Usage" button allows users to manually trigger fuzzy matching to highlight which paragraphs have been used in chapters (chapter-specific color highlighting). This runs automatically on initial draft load and can be manually refreshed on demand. All book paragraphs remain visible for reference and highlighting. **Multi-session workflow:** The platform supports splitting books across multiple sessions - when reloading a draft with existing chapters, the system automatically sets the chapter title to the next chapter number (e.g., "Chapter 4" if 3 chapters exist), clears the editor for fresh input, and maintains all per-draft state so users can seamlessly continue where they left off.

### Technical Implementations
The core application is a Flask web application (`app.py`) providing a REST API. It uses a Python-based EPUB parser (`src/epub_parser.py`) for extracting both plain text and HTML content, including **image extraction** - images from EPUBs are converted to base64 data URIs and embedded in the HTML for inline display. Question and vocabulary generation are handled by an Ollama LLM (`src/question_generator.py`) and executed asynchronously in the background using Python threading for each detected grade level. The system includes a comprehensive draft system that auto-saves progress and tracks chapter generation status. **AI-powered tag generation:** Tags are extracted using only book title and author information (not full text) for faster processing. Tags are generated asynchronously with status tracking (pending → generating → ready → error). **AI-powered description generation:** Book descriptions are auto-generated in two steps: (1) generate synopsis from first 2000 words using `QuestionGenerator.generate_synopsis`, (2) use synopsis + title + author to generate child-friendly description via `QuestionGenerator.generate_description` method. No manual synopsis input required. Database schema includes grade_level column in draft_questions table, tag_status column in draft_books table, description column for AI-generated descriptions, and last_marker_position JSONB column for tracking copy position markers. **Intelligent chapter editing:** The contenteditable div automatically syncs both plain text (`innerText`) and HTML (`innerHTML`) content during manual edits, paste operations, and saves. **Model-agnostic design:** The LLM integration works with ANY Ollama model (thinking models like DeepSeek-R1 or standard models like Llama/Mistral) via intelligent retry strategies, automatic thinking-tag removal, and robust JSON extraction. **GPU-optimized processing:** Controlled via `PARALLEL_GENERATION` environment variable - set to `true` (default) for parallel chapter processing or `false` for sequential processing in GPU-limited environments.

### Feature Specifications
- **Draft System:** Allows incremental processing, auto-saving, and async question generation with real-time status updates. Enforces uniqueness by Gutenberg ID - prevents downloading the same book twice with user-friendly error handling and option to load existing draft.
- **Chapter Management:** Manual chapter splitting via UI, with visual word count validation and fully editable chapter content. Saved chapters can be edited via modal interface supporting both plain text and HTML content editing with word count tracking and persistence via `/api/chapter/<id>` PUT endpoint.
- **AI-Powered Tagging:** Automatic extraction of individual grade-level tags (grade-1, grade-2, etc.) and genre tags using only book title and author. Tags are generated asynchronously and tracked with tag_status column for efficient processing.
- **AI-Powered Description Generation:** Automatically generates child-friendly book descriptions (200-500 characters) asynchronously in two steps: first generates a concise synopsis (max 12 sentences) from the book's first 2000 words, then uses that synopsis along with title and author to create the final description. Description generation automatically starts when downloading a new book (like tag generation). Features async status tracking (pending → generating → ready → error) with frontend polling and duplicate request protection (409 Conflict). **Manual editing:** Users can click "✏️ Edit" to manually edit the description, "💾 Save" to persist changes, or "✨ Regenerate with AI" to generate a new one. Description is copied to the books table during finalization. Descriptions are persisted to the database via the description column with description_status tracking, accessible via PUT `/api/draft/<id>/description` endpoint.
- **EPUB Image Extraction:** Automatically extracts images from EPUB files and embeds them as base64 data URIs in the HTML content. Images are preserved when copying/pasting chapters and displayed inline in the chapter editor.
- **Text Usage Tracking:** Manual tracking system that identifies which book paragraphs have been used in chapters using fuzzy matching (rapidfuzz library). Each chapter is assigned a unique color from a 5-color palette (light blue, green, yellow, pink, purple) with intelligent cycling to ensure adjacent chapters never share the same color. Used paragraphs are visually highlighted with their chapter's color and a subtle left border. System handles minor edits (typos, formatting, word insertions) through hybrid similarity scoring (60% Levenshtein + 40% token-based) with 78% threshold. Runs automatically on initial draft load and can be manually refreshed via "🔄 Refresh Usage" button. Backend returns both used paragraph indices and a mapping of paragraph→chapter number for color assignment. Accessed via `/api/draft/<id>/usage` GET endpoint.
- **Multi-Grade Question Generation:** Generates separate questions and vocabulary for EACH detected grade level. If a book is tagged for grades 2-4, it generates questions specifically for grade-2, grade-3, and grade-4 students.
- **Grade-Specific Vocabulary:** Generates 8 vocabulary words per grade level, with definitions and examples tailored to that grade's comprehension level. Each vocabulary item includes a grade_level field.
- **Automatic Question Regeneration:** Questions are automatically regenerated whenever tags are saved (manual edits) or regenerated (AI-powered). Smart regeneration only processes changed grades: deletes questions for removed grades, generates questions for added grades, and preserves questions for unchanged grades. Automatically handles edge cases like removing all grade tags.
- **Chapter-Level Question Regeneration:** Individual chapters can have their questions regenerated independently via "🔄 Regen" button next to each saved chapter. Uses atomic UPDATE...WHERE status!='generating' pattern for duplicate request protection (409 Conflict). Accessed via `/api/chapter/<id>/regenerate-questions` POST endpoint with async processing and status tracking.
- **Tag Regeneration:** AI-powered tag regeneration button that re-analyzes the book content and automatically triggers question regeneration when new tags are ready. Includes duplicate request protection to prevent concurrent tag generation jobs.
- **Vocabulary Tooltips:** Injected into HTML content for interactive definitions.
- **Book Cover URL:** Option to add a cover image URL to books.
- **Reading Benchmarks:** A modal displaying reading benchmarks (WPM, total words, pages) by grade level.

### System Design Choices
The architecture separates concerns into an EPUB parser, a question generator, and a database manager. Data persistence is managed by PostgreSQL. The system relies on `ON DELETE CASCADE` constraints in the database for data integrity during draft deletion. AI prompt engineering is used to ensure consistent output from the LLM, with robust parsing to handle flexible LLM responses.

### Ollama Priority Queue System
All Ollama LLM API calls are managed through a priority-based FIFO queue system (`src/ollama_queue.py`) to ensure efficient resource utilization and proper task ordering:

- **Priority Levels:**
  - Priority 1 (HIGHEST): Genre and tag generation - processed first as tags determine which questions to generate
  - Priority 2 (MEDIUM): Description and synopsis generation - important for book metadata
  - Priority 3 (LOWEST): Question generation and chapter title generation - can wait as they're generated in bulk

- **Implementation:**
  - Singleton `OllamaQueueManager` with configurable worker threads (default: 1)
  - FIFO ordering within each priority level via `(priority, task_id)` tuple ordering
  - Background worker threads with automatic retry/backoff (3 retries with exponential backoff)
  - Thread-safe execution using Python's `PriorityQueue` with proper locking
  - Graceful shutdown via `atexit` handlers in both Flask (`app.py`) and CLI (`cli.py`) entry points
  - Structured logging with task IDs, priorities, and execution times

- **Integration:**
  - `QuestionGenerator`: All LLM calls (`generate_questions`, `generate_tags`, `generate_description`, `generate_synopsis`) route through queue
  - `ChapterSplitter`: Chapter title generation uses queue with QUESTION priority
  - `ContentAnalyzer`: Front/back matter analysis uses queue with QUESTION priority
  - Existing code signatures preserved via wrapper methods for seamless integration

## Environment Variables
- **PARALLEL_GENERATION** (optional): Controls question generation mode for GPU-limited environments.
  - `true` (default): Process multiple chapters in parallel (faster, requires more GPU memory)
  - `false`: Process one chapter at a time sequentially (slower, GPU-friendly)

## External Dependencies
- **PostgreSQL:** Primary database for storing book metadata, chapters, questions, and vocabulary.
- **Ollama:** Used as the Large Language Model (LLM) for generating comprehension questions, vocabulary, and AI-powered tags.
- **Project Gutenberg:** Source for downloading EPUB books.
- **Flask:** Python web framework for the backend application and API.