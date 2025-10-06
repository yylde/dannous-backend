.PHONY: help install setup test clean run-example list-books

help:
	@echo "EPUB Processing Pipeline - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Install Python dependencies"
	@echo "  make setup          Complete setup (install + Ollama check)"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run test suite"
	@echo "  make test-db        Test database connection"
	@echo ""
	@echo "Processing:"
	@echo "  make run-example    Process Alice in Wonderland (example)"
	@echo "  make list-books     List all processed books"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean          Clean temporary files"
	@echo "  make save-prompts   Save prompt templates to file"

install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt
	@echo "✓ Dependencies installed"

setup: install
	@echo "Checking Ollama installation..."
	@which ollama || (echo "❌ Ollama not found. Install from https://ollama.com" && exit 1)
	@curl -s http://localhost:11434/api/tags > /dev/null 2>&1 || (echo "⚠ Ollama not running. Start with: ollama serve" && exit 1)
	@echo "✓ Ollama is running"
	@ollama list | grep -q llama3.2 || (echo "Pulling llama3.2 model..." && ollama pull llama3.2)
	@echo "✓ Model llama3.2 available"
	@test -f .env || (echo "Creating .env from template..." && cp .env.example .env)
	@echo "✓ Environment file ready"
	@echo ""
	@echo "✅ Setup complete! Edit .env with your DATABASE_URL, then run: make test-db"

test:
	@echo "Running tests..."
	pytest tests/ -v

test-db:
	@echo "Testing database connection..."
	python cli.py test-db

run-example:
	@echo "Processing Alice's Adventures in Wonderland (Gutenberg #11115)..."
	python cli.py process-gutenberg 11115 --age-range "8-12" --reading-level "beginner"

list-books:
	python cli.py list-books

save-prompts:
	python cli.py save-prompts

clean:
	@echo "Cleaning temporary files..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	rm -f gutenberg_*.epub
	@echo "✓ Cleaned"