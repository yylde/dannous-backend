"""Question generation using Ollama LLM."""

import json
import logging
import re
import time
from typing import List, Dict, Tuple
import ollama
from .config import settings

logger = logging.getLogger(__name__)


def remove_thinking_tokens(response: str) -> str:
    """
    Remove thinking tokens/tags from LLM responses.
    
    Handles various thinking tag formats used by different models:
    - <think>...</think>
    - <thinking>...</thinking>
    - <thought>...</thought>
    - Special tokens like <｜begin▁of▁thinking｜>
    - And variations with attributes
    
    Args:
        response: Raw response string from the model
        
    Returns:
        Cleaned response with thinking tokens removed
    """
    # Remove <think> tags and their content
    response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <thinking> tags and their content
    response = re.sub(r'<thinking>.*?</thinking>', '', response, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <thought> tags and their content
    response = re.sub(r'<thought>.*?</thought>', '', response, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <answer> tags (but keep the content)
    response = re.sub(r'<answer>', '', response, flags=re.IGNORECASE)
    response = re.sub(r'</answer>', '', response, flags=re.IGNORECASE)
    
    # Remove any remaining thinking-related tags with attributes
    response = re.sub(r'<think[^>]*>.*?</think>', '', response, flags=re.DOTALL | re.IGNORECASE)
    response = re.sub(r'<thinking[^>]*>.*?</thinking>', '', response, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove special DeepSeek thinking tokens
    response = re.sub(r'<｜begin▁of▁thinking｜>.*?<｜end▁of▁thinking｜>', '', response, flags=re.DOTALL)
    response = re.sub(r'<｜begin▁of▁sentence｜>', '', response)
    response = re.sub(r'<｜end▁of▁sentence｜>', '', response)
    
    # Clean up extra whitespace
    response = re.sub(r'\n\s*\n+', '\n\n', response)
    response = response.strip()
    
    return response


class QuestionGenerator:
    """Generate comprehension questions using Ollama."""
    
    def __init__(self, model: str = None):
        """Initialize question generator."""
        self.model = model or settings.ollama_model
        self.base_url = settings.ollama_base_url
        self.timeout = settings.ollama_timeout
        
        # Load prompt template
        self.prompt_template = self._load_prompt_template()
    
    def _load_prompt_template(self) -> str:
        """Load question generation prompt template for a specific grade level."""
        return """You are an expert educator creating reading comprehension questions for children in {grade_level}.

Book: "{title}" by {author}
Chapter {chapter_number}: {chapter_title}
Target Grade: {grade_level}
Reading Level: {reading_level}
Age Range: {age_range}

Chapter Text:
{chapter_text}

CRITICAL: All content MUST be strictly age-appropriate for {grade_level} students (ages {age_range}). Use vocabulary, concepts, and themes that match their developmental stage and cognitive abilities.

Generate exactly {num_questions} open-ended comprehension questions appropriate for {grade_level} students:
1. Are NOT multiple choice or yes/no questions
2. Start with "Why" or "How" to encourage critical thinking
3. Require {min_words}-{max_words} word thoughtful answers
4. Test understanding beyond simple recall
5. Are specifically tailored for {grade_level} reading and comprehension abilities
6. Focus on themes, character motivation, cause-and-effect, or inference
7. Use language and concepts that are developmentally appropriate for ages {age_range}
8. Avoid abstract or complex themes beyond {grade_level} comprehension

Additionally, identify {vocab_count} words that might be difficult for a {grade_level} student. For each word, provide:
- word: the difficult word (must appear in the chapter text)
- definition: a child-friendly definition appropriate for {grade_level}
- example: a simple example sentence using the word in context

IMPORTANT for vocabulary selection:
- DO NOT include character names (e.g., "Alice", "Hatter", "Queen") - these are proper nouns and don't need definitions
- DO include country names and geographical locations (e.g., "Wonderland", "England") - these help students learn geography
- Focus on challenging adjectives, verbs, and descriptive words that enhance comprehension
- Select vocabulary that is challenging yet achievable for {grade_level} students
- Ensure definitions use simple language appropriate for ages {age_range}
- Examples should relate to situations and experiences familiar to {grade_level} children

CRITICAL INSTRUCTIONS:
- Respond with ONLY valid JSON - no markdown, no code blocks, no explanations
- DO NOT nest "questions" arrays inside questions - keep it flat
- Each question must have: "text", "keywords" (array), "difficulty"
- Each vocabulary item must have: "word", "definition", "example"

EXACT FORMAT (copy this structure):
{{"questions":[{{"text":"Why did the character...","keywords":["character","action"],"difficulty":"medium"}},{{"text":"How does the setting...","keywords":["setting","mood"],"difficulty":"easy"}}],"vocabulary":[{{"word":"example","definition":"simple meaning","example":"Sample sentence using example."}}]}}

Your entire response must be valid JSON starting with {{ and ending with }}"""

    def _parse_response(self, response: str, expected_count: int) -> Tuple[List[Dict], List[Dict], List[str]]:
        """
        Parse JSON response from LLM with robust error handling.
        Works with ANY Ollama model - thinking or non-thinking.
        
        Returns:
            Tuple of (questions, vocabulary, tags)
        """
        try:
            original_response = response
            
            # STEP 1: Remove thinking tokens (safe even if no thinking tags present)
            response = remove_thinking_tokens(response)
            
            # STEP 2: Clean up response
            response = response.strip()
            
            # Remove markdown code blocks if present
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0].strip()
            elif '```' in response:
                # Handle generic code blocks
                parts = response.split('```')
                for part in parts:
                    part = part.strip()
                    if part.startswith('{') and part.endswith('}'):
                        response = part
                        break
            
            # STEP 3: Extract JSON using regex (more robust)
            # Try to find the largest valid JSON object
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
            
            if 'questions' not in data:
                logger.warning("No 'questions' key in response")
                return [], [], []
            
            # Parse questions with better validation
            questions = []
            raw_questions = data['questions']
            
            # Handle nested questions arrays (flatten if needed)
            if raw_questions and isinstance(raw_questions[0], dict) and 'questions' in raw_questions[0]:
                logger.warning("Detected nested 'questions' array - flattening")
                raw_questions = raw_questions[0]['questions']
            
            for i, q in enumerate(raw_questions[:expected_count]):
                # Skip non-dict items
                if not isinstance(q, dict):
                    logger.warning(f"Question {i} is not a dict: {q}")
                    continue
                
                # Validate question structure - accept both 'text' and 'question' keys
                question_text = q.get('text') or q.get('question')
                if not question_text:
                    logger.warning(f"Question {i} missing 'text' field: {q}")
                    continue
                
                questions.append({
                    'text': question_text.strip(),
                    'keywords': q.get('keywords', []),
                    'difficulty': q.get('difficulty', 'medium')
                })
            
            # Parse vocabulary with more lenient validation
            vocabulary = []
            if 'vocabulary' in data and isinstance(data['vocabulary'], list):
                for i, v in enumerate(data['vocabulary']):
                    # More flexible validation
                    if isinstance(v, dict) and 'word' in v and 'definition' in v:
                        vocabulary.append({
                            'word': str(v['word']).strip(),
                            'definition': str(v['definition']).strip(),
                            'example': str(v.get('example', '')).strip()
                        })
                    else:
                        logger.warning(f"Vocabulary item {i} has invalid structure: {v}")
            
            # Parse tags with lenient validation
            tags = []
            if 'tags' in data and isinstance(data['tags'], list):
                tags = [str(tag).strip() for tag in data['tags'] if tag]
            else:
                logger.warning("No 'tags' key in response or tags is not a list, defaulting to empty array")
            
            logger.info(f"Successfully parsed {len(questions)} questions, {len(vocabulary)} vocabulary words, and {len(tags)} tags")
            return questions, vocabulary, tags
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Response was: {response[:500]}")
            return [], [], []
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            logger.debug(f"Response was: {response[:500]}")
            return [], [], []
    def generate_questions(
        self,
        title: str,
        author: str,
        chapter_number: int,
        chapter_title: str,
        chapter_text: str,
        reading_level: str,
        age_range: str,
        grade_level: str = None,
        num_questions: int = None,
        vocab_count: int = 8
    ) -> Tuple[List[Dict[str, any]], List[Dict[str, str]]]:
        """
        Generate questions and vocabulary for a chapter at a specific grade level.
        
        Args:
            grade_level: Target grade (e.g., "grade-3", "grade-4")
            vocab_count: Number of vocabulary words to generate
        
        Returns:
            Tuple of (questions_list, vocabulary_list)
        """
        if num_questions is None:
            num_questions = settings.questions_per_chapter
        
        if grade_level is None:
            grade_level = reading_level
        
        logger.info(
            f"Generating {num_questions} questions and {vocab_count} vocabulary words for "
            f"{grade_level} - Chapter {chapter_number}: {chapter_title}"
        )
        
        # Truncate chapter text if too long (to avoid context limits)
        max_context_words = 2000
        words = chapter_text.split()
        if len(words) > max_context_words:
            chapter_text = ' '.join(words[:max_context_words]) + "..."
            logger.debug(f"Truncated chapter text to {max_context_words} words")
        
        # Build prompt
        prompt = self.prompt_template.format(
            title=title,
            author=author,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            reading_level=reading_level,
            age_range=age_range,
            grade_level=grade_level,
            num_questions=num_questions,
            vocab_count=vocab_count,
            min_words=settings.min_answer_words,
            max_words=settings.max_answer_words
        )
        
        # Call Ollama with intelligent retries (model-agnostic)
        max_retries = 3
        strategies = [
            ('free-form', False),      # Try 1: Free-form (works with thinking models)
            ('free-form', False),      # Try 2: Retry free-form
            ('json-format', True)      # Try 3: Force JSON format (for non-thinking models)
        ]
        
        for attempt in range(max_retries):
            strategy_name, use_json_format = strategies[attempt]
            try:
                logger.info(f"Attempt {attempt + 1}/{max_retries} using {strategy_name} strategy")
                response = self._call_ollama(prompt, force_json_format=use_json_format)
                questions, vocabulary, _ = self._parse_response(response, num_questions)
                
                if questions:
                    logger.info(f"✓ Success with {strategy_name}! Generated {len(questions)} questions and {len(vocabulary)} vocabulary words for {grade_level}")
                    return questions, vocabulary
                else:
                    logger.warning(f"Attempt {attempt + 1}: No questions parsed from response")
                
            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1} ({strategy_name}): JSON parsing failed - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} ({strategy_name}): {type(e).__name__} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: generate generic questions and empty vocabulary
        logger.warning("Using fallback questions")
        return self._generate_fallback_questions(chapter_title, num_questions), []
    
    def _call_ollama(self, prompt: str, force_json_format: bool = False) -> str:
        """Call Ollama API with model-agnostic settings.
        
        This method is designed to work with ANY Ollama model:
        - Thinking models (DeepSeek-R1, etc.) - outputs <think> tags
        - Standard models (Llama, Mistral, etc.) - direct JSON output
        - Any model with custom response formats
        
        Args:
            prompt: The prompt to send to the model
            force_json_format: If True, uses format='json' (disables thinking mode)
        
        Returns:
            Raw model response string
        """
        try:
            # Build request options
            options = {
                'temperature': 0.7,
                'top_p': 0.9,
                'num_predict': 4000  # Generous token limit for all models
            }
            
            # Decide whether to use format='json'
            # - If force_json_format=True: Use it (for retry attempts)
            # - Otherwise: Don't use it (allows thinking models to work)
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
            
            # Call Ollama
            response = ollama.generate(**generate_params)
            raw_response = response['response']
            
            # Log diagnostic info
            has_thinking_tags = '<think>' in raw_response.lower() or '<thinking>' in raw_response.lower()
            logger.debug(f"Model: {self.model}")
            logger.debug(f"Response length: {len(raw_response)} chars")
            logger.debug(f"Contains thinking tags: {has_thinking_tags}")
            logger.debug(f"First 500 chars: {raw_response[:500]}")
            
            return raw_response
            
        except Exception as e:
            logger.error(f"Ollama API call failed with model {self.model}: {e}")
            raise
    
    def _generate_fallback_questions(
        self,
        chapter_title: str,
        num_questions: int
    ) -> List[Dict]:
        """Generate generic fallback questions."""
        fallback = [
            {
                'text': f"Why do you think the events in '{chapter_title}' happened the way they did?",
                'keywords': ['reason', 'cause', 'because', 'event'],
                'difficulty': 'medium'
            },
            {
                'text': f"How did the characters in '{chapter_title}' change or grow?",
                'keywords': ['change', 'character', 'development', 'growth'],
                'difficulty': 'medium'
            },
            {
                'text': f"What lesson or message do you think '{chapter_title}' is trying to teach?",
                'keywords': ['lesson', 'message', 'theme', 'moral'],
                'difficulty': 'medium'
            },
            {
                'text': f"How would you feel if you were in the situation described in '{chapter_title}'?",
                'keywords': ['feeling', 'emotion', 'situation', 'experience'],
                'difficulty': 'easy'
            },
            {
                'text': f"Why is '{chapter_title}' important to the overall story?",
                'keywords': ['important', 'significance', 'story', 'plot'],
                'difficulty': 'medium'
            }
        ]
        
        return fallback[:num_questions]
    
    def generate_tags(
        self,
        title: str,
        author: str,
        reading_level: str,
        age_range: str
    ) -> List[str]:
        """
        Generate tags (genre + grade level) for a book using only the title.
        
        Args:
            title: Book title
            author: Book author
            reading_level: Reading level
            age_range: Age range
        
        Returns:
            List of tags (e.g., ["adventure", "fantasy", "grades-4-6"])
        """
        logger.info(f"Generating tags for book: {title} by {author}")
        
        # Build prompt for tag generation (using only title)
        prompt = f"""You are an expert librarian and educator analyzing children's books.

Book: "{title}" by {author}
Reading Level: {reading_level}
Age Range: {age_range}

Based on the book title and author, provide appropriate tags:
1. Genre tags (as many as applicable, 1-4 tags): Select from: "adventure", "fantasy", "mystery", "historical-fiction", "science-fiction", "realistic-fiction", "humor", "horror", "romance", "poetry", "biography", "educational"
2. Individual grade-level tags (MAXIMUM 4 GRADES): Select the 4 most likely grades from: "grade-K", "grade-1", "grade-2", "grade-3", "grade-4", "grade-5", "grade-6", "grade-7", "grade-8", "grade-9", "grade-10", "grade-11", "grade-12"
   - Include ONLY the 4 most appropriate consecutive grades for this book
   - For example, if suitable for 3rd-6th graders, include: "grade-3", "grade-4", "grade-5", "grade-6"
   - LIMIT: Maximum 4 grade tags total

CRITICAL INSTRUCTIONS:
- Respond with ONLY valid JSON - no markdown, no code blocks, no explanations
- Return a simple array of strings
- Include 1-4 genre tags + EXACTLY 4 individual grade tags (or fewer if the book has a narrower audience)
- Focus on the MOST LIKELY grades for this book

EXACT FORMAT (copy this structure):
{{"tags":["adventure","fantasy","grade-3","grade-4","grade-5","grade-6"]}}

Your entire response must be valid JSON starting with {{ and ending with }}"""
        
        # Call Ollama with intelligent retries (model-agnostic)
        max_retries = 3
        strategies = [
            ('free-form', False),      # Try 1: Free-form (works with thinking models)
            ('free-form', False),      # Try 2: Retry free-form
            ('json-format', True)      # Try 3: Force JSON format (for non-thinking models)
        ]
        
        for attempt in range(max_retries):
            strategy_name, use_json_format = strategies[attempt]
            try:
                logger.info(f"Tag generation attempt {attempt + 1}/{max_retries} using {strategy_name} strategy")
                response = self._call_ollama(prompt, force_json_format=use_json_format)
                tags = self._parse_tags_response(response)
                
                if tags:
                    logger.info(f"✓ Success with {strategy_name}! Generated {len(tags)} tags for book: {tags}")
                    return tags
                else:
                    logger.warning(f"Attempt {attempt + 1}: No tags parsed from response")
                
            except json.JSONDecodeError as e:
                logger.warning(f"Tag attempt {attempt + 1} ({strategy_name}): JSON parsing failed - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Tag attempt {attempt + 1} ({strategy_name}): {type(e).__name__} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: return generic tags based on reading level
        logger.warning("Using fallback tags")
        return self._generate_fallback_tags(reading_level)
    
    def _parse_tags_response(self, response: str) -> List[str]:
        """Parse tags-only response from LLM.
        Works with ANY Ollama model - thinking or non-thinking."""
        try:
            original_response = response
            
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
            
            # Extract tags
            tags = []
            if 'tags' in data and isinstance(data['tags'], list):
                tags = [str(tag).strip() for tag in data['tags'] if tag]
            
            return tags
            
        except Exception as e:
            logger.error(f"Error parsing tags response: {e}")
            logger.debug(f"Response was: {response[:500]}")
            return []
    
    def generate_description(
        self,
        title: str,
        author: str,
        synopsis: str = None
    ) -> str:
        """
        Generate a book description using only the title, author, and optional synopsis.
        
        Args:
            title: Book title
            author: Book author
            synopsis: Optional synopsis or brief information about the book
        
        Returns:
            Generated description string (200-500 characters)
        """
        logger.info(f"Generating description for book: {title} by {author}")
        
        # Build prompt for description generation
        synopsis_text = f"\nSynopsis: {synopsis}" if synopsis else ""
        
        prompt = f"""You are an expert librarian writing book descriptions for children's books.

Book: "{title}" by {author}{synopsis_text}

Based on the title, author{', and synopsis' if synopsis else ''}, write an engaging description for this book (200-500 characters).

The description should:
- Be engaging and appropriate for children
- Capture the essence and appeal of the book
- Be 200-500 characters long
- Not use quotation marks
- Be a single paragraph

CRITICAL INSTRUCTIONS:
- Respond with ONLY the description text
- NO markdown, NO code blocks, NO explanations
- Just the description paragraph itself

Your response:"""
        
        # Call Ollama with retries
        max_retries = 2
        for attempt in range(max_retries):
            try:
                logger.info(f"Description generation attempt {attempt + 1}/{max_retries}")
                response = self._call_ollama(prompt, force_json_format=False)
                
                # Clean up response
                description = remove_thinking_tokens(response).strip()
                
                # Remove quotes if present
                description = description.strip('"').strip("'")
                
                # Truncate if too long
                if len(description) > 500:
                    description = description[:500].rsplit(' ', 1)[0] + '...'
                
                # Ensure minimum length
                if len(description) >= 50:
                    logger.info(f"✓ Generated description ({len(description)} chars): {description[:100]}...")
                    return description
                else:
                    logger.warning(f"Attempt {attempt + 1}: Description too short ({len(description)} chars)")
                
            except Exception as e:
                logger.warning(f"Description attempt {attempt + 1}: {type(e).__name__} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: return a generic description
        logger.warning("Using fallback description")
        return f"{title} by {author} is a captivating children's book that engages young readers with its compelling story and memorable characters."
    
    def _generate_fallback_tags(self, reading_level: str) -> List[str]:
        """Generate fallback tags based on reading level."""
        # Map reading level to individual grade tags
        level_map = {
            'beginner': ['grade-K', 'grade-1', 'grade-2'],
            'early-reader': ['grade-1', 'grade-2', 'grade-3'],
            'intermediate': ['grade-4', 'grade-5', 'grade-6'],
            'advanced': ['grade-7', 'grade-8', 'grade-9'],
            'young-adult': ['grade-10', 'grade-11', 'grade-12']
        }
        
        grade_tags = level_map.get(reading_level, ['grade-4', 'grade-5', 'grade-6'])
        return ['fiction'] + grade_tags


def save_prompt_template(filepath: str = "prompts/question_generation.txt"):
    """Save the prompt template to a file for documentation."""
    import os
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    generator = QuestionGenerator()
    with open(filepath, 'w') as f:
        f.write(generator.prompt_template)
    
    logger.info(f"Saved prompt template to {filepath}")