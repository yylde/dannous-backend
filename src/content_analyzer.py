"""LLM-based content analysis for detecting Gutenberg boilerplate and metadata."""

import json
import logging
import re
import time
from typing import Dict, List, Tuple
import ollama
from .config import settings
from .ollama_queue import queue_ollama_call, TaskPriority

logger = logging.getLogger(__name__)


def remove_thinking_tokens(response: str) -> str:
    """
    Remove thinking tokens/tags from LLM responses.
    Works with any model - thinking or non-thinking.
    """
    # Remove <think> tags and their content
    response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL | re.IGNORECASE)
    response = re.sub(r'<thinking>.*?</thinking>', '', response, flags=re.DOTALL | re.IGNORECASE)
    response = re.sub(r'<thought>.*?</thought>', '', response, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <answer> tags (but keep the content)
    response = re.sub(r'<answer>', '', response, flags=re.IGNORECASE)
    response = re.sub(r'</answer>', '', response, flags=re.IGNORECASE)
    
    # Remove special DeepSeek thinking tokens
    response = re.sub(r'<｜begin▁of▁thinking｜>.*?<｜end▁of▁thinking｜>', '', response, flags=re.DOTALL)
    response = re.sub(r'<｜begin▁of▁sentence｜>', '', response)
    response = re.sub(r'<｜end▁of▁sentence｜>', '', response)
    
    # Clean up extra whitespace
    response = re.sub(r'\n\s*\n+', '\n\n', response)
    response = response.strip()
    
    return response


class ContentAnalyzer:
    """Analyze book content using LLM to detect boilerplate and metadata."""
    
    def __init__(self, model: str = None):
        """Initialize content analyzer."""
        self.model = model or settings.ollama_model
    
    def _call_ollama_direct(self, prompt: str, force_json_format: bool = False) -> str:
        """Direct Ollama API call (internal, not queued).
        
        Works with ANY Ollama model - thinking or non-thinking.
        """
        options = {
            'temperature': 0.3,
            'num_predict': 200
        }
        
        generate_params = {
            'model': self.model,
            'prompt': prompt,
            'options': options
        }
        
        if force_json_format:
            generate_params['format'] = 'json'
            logger.debug(f"Using format='json' for model: {self.model}")
        else:
            logger.debug(f"Using free-form output for model: {self.model}")
        
        response = ollama.generate(**generate_params)
        raw_response = response['response']
        
        logger.debug(f"Model: {self.model}, Response length: {len(raw_response)} chars")
        return raw_response
    
    def _call_ollama(self, prompt: str, force_json_format: bool = False, priority: TaskPriority = TaskPriority.QUESTION, task_name: str = "") -> str:
        """Call Ollama API through the priority queue.
        
        Args:
            prompt: The prompt to send to the model
            force_json_format: If True, uses format='json' (disables thinking mode)
            priority: Task priority level (GENRE_TAG=1, DESCRIPTION=2, QUESTION=3)
            task_name: Descriptive name for queue logging
        
        Returns:
            Raw model response string
        """
        try:
            return queue_ollama_call(
                self._call_ollama_direct,
                priority,
                task_name or "content_analyzer",
                prompt,
                force_json_format
            )
        except Exception as e:
            logger.error(f"Queued Ollama API call failed: {e}")
            raise
    
    def analyze_book_structure(self, text: str) -> Dict:
        """
        Analyze book to identify:
        - Pages to delete (Gutenberg boilerplate)
        - Metadata chapters (TOC, Preface, etc.) - keep but no questions
        - Main content chapters
        """
        logger.info("Analyzing book structure with LLM...")
        
        # Split text into pages (approximately 250 words per page)
        pages = self._split_into_pages(text)
        total_pages = len(pages)
        
        logger.info(f"Book has approximately {total_pages} pages")
        
        # Get first and last 20 pages
        first_pages = pages[:min(20, total_pages)]
        last_pages = pages[max(0, total_pages - 20):] if total_pages > 20 else []
        
        # Analyze front matter
        front_analysis = self._analyze_front_matter(first_pages)
        
        # Analyze back matter
        back_analysis = self._analyze_back_matter(last_pages, total_pages)
        
        return {
            'total_pages': total_pages,
            'delete_pages': front_analysis['delete_pages'] + back_analysis['delete_pages'],
            'metadata_pages': front_analysis['metadata_pages'] + back_analysis['metadata_pages'],
            'content_start_page': front_analysis['content_start_page'],
            'content_end_page': back_analysis['content_end_page']
        }
    
    def _split_into_pages(self, text: str, words_per_page: int = 250) -> List[str]:
        """Split text into approximate pages."""
        words = text.split()
        pages = []
        
        for i in range(0, len(words), words_per_page):
            page_words = words[i:i + words_per_page]
            pages.append(' '.join(page_words))
        
        return pages
    
    def _analyze_front_matter(self, first_pages: List[str]) -> Dict:
        """Analyze first 20 pages to detect Gutenberg header and book metadata."""
        
        # Combine first pages for analysis
        sample_text = '\n\n[PAGE BREAK]\n\n'.join(first_pages)
        
        prompt = f"""Analyze the beginning of this book to identify different sections.

The text contains approximately {len(first_pages)} pages. Each page is separated by [PAGE BREAK].

Your task:
1. Identify which pages contain Project Gutenberg legal text/license (DELETE these)
2. Identify which pages contain book metadata like Table of Contents, Preface, Introduction, Dedication (KEEP but mark as METADATA - no comprehension questions needed)
3. Identify where the actual story/main content begins (CONTENT)

Book beginning:
{sample_text[:4000]}

Respond ONLY with valid JSON:
{{
  "delete_pages": [1, 2],
  "metadata_pages": [3, 4, 5],
  "content_start_page": 6,
  "reasoning": "Brief explanation of decisions"
}}

Page numbers should be 1-indexed. If Gutenberg text appears on pages 1-2, then delete_pages=[1,2].
If no Gutenberg text found, delete_pages should be empty [].
If no metadata (TOC/Preface/etc), metadata_pages should be empty []."""

        # Use intelligent retry strategy (model-agnostic)
        max_retries = 3
        strategies = [
            ('free-form', False),      # Try 1: Free-form (works with thinking models)
            ('free-form', False),      # Try 2: Retry free-form
            ('json-format', True)      # Try 3: Force JSON format (for non-thinking models)
        ]
        
        for attempt in range(max_retries):
            strategy_name, use_json_format = strategies[attempt]
            try:
                logger.debug(f"Front matter analysis attempt {attempt + 1}/{max_retries} using {strategy_name}")
                response = self._call_ollama(
                    prompt, 
                    force_json_format=use_json_format,
                    priority=TaskPriority.QUESTION,
                    task_name="analyze_front_matter"
                )
                result = self._parse_json_response(response)
                
                if result:
                    logger.info(f"✓ Success with {strategy_name}!")
                    logger.info(f"Front matter analysis: {result.get('reasoning', 'No reasoning provided')}")
                    logger.info(f"Delete pages: {result.get('delete_pages', [])}")
                    logger.info(f"Metadata pages: {result.get('metadata_pages', [])}")
                    logger.info(f"Content starts at page: {result.get('content_start_page', 1)}")
                    return result
                else:
                    logger.warning(f"Attempt {attempt + 1}: No valid result parsed")
                
            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1} ({strategy_name}): JSON parsing failed - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} ({strategy_name}): {type(e).__name__} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: assume first 2 pages are Gutenberg
        logger.warning("Using fallback front matter detection")
        return {
            'delete_pages': [1, 2],
            'metadata_pages': [],
            'content_start_page': 3,
            'reasoning': 'Fallback: assumed pages 1-2 are Gutenberg'
        }
    
    def _analyze_back_matter(self, last_pages: List[str], total_pages: int) -> Dict:
        """Analyze last 20 pages to detect Gutenberg footer and book back matter."""
        
        if not last_pages:
            return {'delete_pages': [], 'metadata_pages': [], 'content_end_page': total_pages}
        
        # Combine last pages for analysis
        sample_text = '\n\n[PAGE BREAK]\n\n'.join(last_pages)
        
        # Calculate page numbers (these are the last N pages)
        start_page = total_pages - len(last_pages) + 1
        
        prompt = f"""Analyze the ending of this book to identify different sections.

The book has {total_pages} total pages. These are the LAST {len(last_pages)} pages (pages {start_page}-{total_pages}).
Each page is separated by [PAGE BREAK].

Your task:
1. Identify which pages contain Project Gutenberg legal text/license/donation info (DELETE these)
2. Identify which pages contain book back matter like Epilogue, Afterword, Appendix, Notes (KEEP but mark as METADATA - no comprehension questions needed)
3. Identify where the actual story/main content ends (CONTENT)

Book ending:
{sample_text[:4000]}

Respond ONLY with valid JSON:
{{
  "delete_pages": [{total_pages - 1}, {total_pages}],
  "metadata_pages": [{total_pages - 3}, {total_pages - 2}],
  "content_end_page": {total_pages - 4},
  "reasoning": "Brief explanation"
}}

Page numbers should match the actual page numbers in the book (e.g., if book is 200 pages and last page has Gutenberg text, use 200).
If no Gutenberg text found, delete_pages should be empty [].
If no back matter (Epilogue/Appendix/etc), metadata_pages should be empty []."""

        # Use intelligent retry strategy (model-agnostic)
        max_retries = 3
        strategies = [
            ('free-form', False),      # Try 1: Free-form (works with thinking models)
            ('free-form', False),      # Try 2: Retry free-form
            ('json-format', True)      # Try 3: Force JSON format (for non-thinking models)
        ]
        
        for attempt in range(max_retries):
            strategy_name, use_json_format = strategies[attempt]
            try:
                logger.debug(f"Back matter analysis attempt {attempt + 1}/{max_retries} using {strategy_name}")
                response = self._call_ollama(
                    prompt, 
                    force_json_format=use_json_format,
                    priority=TaskPriority.QUESTION,
                    task_name="analyze_back_matter"
                )
                result = self._parse_json_response(response)
                
                if result:
                    logger.info(f"✓ Success with {strategy_name}!")
                    logger.info(f"Back matter analysis: {result.get('reasoning', 'No reasoning provided')}")
                    logger.info(f"Delete pages: {result.get('delete_pages', [])}")
                    logger.info(f"Metadata pages: {result.get('metadata_pages', [])}")
                    logger.info(f"Content ends at page: {result.get('content_end_page', total_pages)}")
                    return result
                else:
                    logger.warning(f"Attempt {attempt + 1}: No valid result parsed")
                
            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1} ({strategy_name}): JSON parsing failed - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} ({strategy_name}): {type(e).__name__} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: assume last 2 pages are Gutenberg
        logger.warning("Using fallback back matter detection")
        return {
            'delete_pages': [total_pages - 1, total_pages] if total_pages > 2 else [],
            'metadata_pages': [],
            'content_end_page': total_pages - 2 if total_pages > 2 else total_pages,
            'reasoning': 'Fallback: assumed last 2 pages are Gutenberg'
        }
    
    def _parse_json_response(self, response: str) -> Dict:
        """Parse JSON response from LLM.
        Works with ANY Ollama model - thinking or non-thinking."""
        try:
            # STEP 1: Remove thinking tokens (safe even if no thinking tags present)
            response = remove_thinking_tokens(response)
            
            # STEP 2: Clean up response
            response = response.strip()
            
            # Remove markdown code blocks if present
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0].strip()
            elif '```' in response:
                parts = response.split('```')
                for part in parts:
                    part = part.strip()
                    if part.startswith('{') and part.endswith('}'):
                        response = part
                        break
            
            # STEP 3: Extract JSON using regex (more robust)
            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            json_matches = re.findall(json_pattern, response, re.DOTALL)
            
            if json_matches:
                # Take the longest match (usually the complete JSON)
                response = max(json_matches, key=len)
            else:
                # Fallback: try to find JSON boundaries manually
                if not response.startswith('{'):
                    start_idx = response.find('{')
                    if start_idx != -1:
                        response = response[start_idx:]
                
                if not response.endswith('}'):
                    end_idx = response.rfind('}')
                    if end_idx != -1:
                        response = response[:end_idx + 1]
            
            # STEP 4: Parse JSON
            data = json.loads(response)
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Response was: {response[:200]}")
            return None
    
    def apply_analysis(self, text: str, analysis: Dict) -> Tuple[str, List[Dict]]:
        """
        Apply the analysis results to extract clean content and metadata sections.
        
        Returns:
            Tuple of (cleaned_text, metadata_sections)
            - cleaned_text: Main content with Gutenberg removed
            - metadata_sections: List of {title, content, page_range} for metadata chapters
        """
        pages = self._split_into_pages(text)
        total_pages = len(pages)
        
        delete_pages = set(analysis.get('delete_pages', []))
        metadata_pages = set(analysis.get('metadata_pages', []))
        
        # Separate pages
        content_pages = []
        metadata_sections = []
        current_metadata = []
        current_metadata_start = None
        
        for i, page in enumerate(pages, start=1):
            if i in delete_pages:
                # Skip Gutenberg pages
                continue
            elif i in metadata_pages:
                # Collect metadata pages
                if current_metadata_start is None:
                    current_metadata_start = i
                current_metadata.append(page)
            else:
                # If we were collecting metadata, save it
                if current_metadata:
                    metadata_sections.append({
                        'content': '\n\n'.join(current_metadata),
                        'page_range': (current_metadata_start, i - 1),
                        'title': self._extract_metadata_title(current_metadata[0])
                    })
                    current_metadata = []
                    current_metadata_start = None
                
                # Add to content
                content_pages.append(page)
        
        # Handle trailing metadata
        if current_metadata:
            metadata_sections.append({
                'content': '\n\n'.join(current_metadata),
                'page_range': (current_metadata_start, total_pages),
                'title': self._extract_metadata_title(current_metadata[0])
            })
        
        cleaned_text = '\n\n'.join(content_pages)
        
        logger.info(f"Extracted {len(content_pages)} content pages, {len(metadata_sections)} metadata sections")
        
        return cleaned_text, metadata_sections
    
    def _extract_metadata_title(self, first_page: str) -> str:
        """Extract title from first page of metadata section."""
        # Get first line that's not empty
        lines = [line.strip() for line in first_page.split('\n') if line.strip()]
        if lines:
            # First substantial line is likely the title
            for line in lines[:3]:
                if len(line) > 3 and len(line) < 100:
                    return line
        
        return "Metadata Section"