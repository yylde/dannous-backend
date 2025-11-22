"""Question generation using OpenRouter LLM."""

import json
import logging
import re
import time
import os
from typing import List, Dict, Tuple, Optional
from openai import OpenAI, RateLimitError
from .config import settings
from .ollama_queue import queue_ollama_call, TaskPriority

logger = logging.getLogger(__name__)


def remove_thinking_tokens(response: str) -> str:
    """
    Remove thinking tokens/tags from LLM responses.
    
    Handles various thinking tag formats used by different models:
    - <think>...</think>
    - <thinking>...</thinking>
    - <thought>...</thought>
    - Special tokens like <｜begin of thinking｜>
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
    response = re.sub(r'<｜begin of thinking｜>.*?<｜end of thinking｜>', '', response, flags=re.DOTALL)
    response = re.sub(r'<｜begin of sentence｜>', '', response)
    response = re.sub(r'<｜end of sentence｜>', '', response)
    
    # Clean up extra whitespace
    response = re.sub(r'\n\s*\n+', '\n\n', response)
    response = response.strip()
    
    return response


class QuestionGenerator:
    """Generate comprehension questions using OpenRouter LLM."""
    
    def __init__(self, model: str = None):
        """Initialize question generator."""
        # Default to configured free model if not specified
        self.model = model or settings.openrouter_free_model
        
        # Initialize OpenAI client for OpenRouter
        api_key = settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            logger.warning("OPENROUTER_API_KEY not found in environment variables")
            
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        
        # Load prompt template
        self.prompt_template = self._load_prompt_template()
    
    def _load_prompt_template(self) -> str:
        """Load question generation prompt template for a specific grade level."""
        return """You are an expert educator creating reading comprehension questions for children in {grade_level}.

Book: "{title}" by {author}
Chapter {chapter_number}: {chapter_title}
Target Grade: {grade_level}
Reading Level: {reading_level}

Chapter Text:
{chapter_text}

CRITICAL: All content MUST be strictly appropriate for {grade_level} students. Use vocabulary, concepts, and themes that match their developmental stage and cognitive abilities.

Generate exactly {num_questions} open-ended comprehension questions appropriate for {grade_level} students:
1. Are NOT multiple choice or yes/no questions
2. Start with "Why" or "How" to encourage critical thinking
3. Require {min_words}-{max_words} word thoughtful answers
4. Test understanding beyond simple recall
5. Are specifically tailored for {grade_level} reading and comprehension abilities
6. Focus on themes, character motivation, cause-and-effect, or inference
7. Use language and concepts that are developmentally appropriate for {grade_level}
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
- Ensure definitions use simple language appropriate for {grade_level}
- Examples should relate to situations and experiences familiar to {grade_level} children
- DO NOT choose words with the same root (e.g., do not include both "travel" and "traveling") - select unique word families only

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
        Works with ANY model - thinking or non-thinking.
        
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
        vocab_count: int = 8,
        book_id: str = None,
        chapter_id: str = None,
        use_queue: bool = True
    ) -> Tuple[List[Dict[str, any]], List[Dict[str, str]]]:
        """
        Generate questions and vocabulary for a chapter at a specific grade level.
        
        Args:
            grade_level: Target grade (e.g., "grade-3", "grade-4")
            vocab_count: Number of vocabulary words to generate
            book_id: Book ID
            chapter_id: Chapter ID
            use_queue: If True, use queue; if False, call LLM directly
        
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
            grade_level=grade_level,
            num_questions=num_questions,
            vocab_count=vocab_count,
            min_words=settings.min_answer_words,
            max_words=settings.max_answer_words
        )
        
        # Call LLM (queue or direct based on use_queue parameter)
        try:
            if use_queue:
                response = self._call_ollama(
                    prompt, 
                    force_json_format=False,
                    priority=TaskPriority.QUESTION,
                    task_name=f"generate_questions_{title}_ch{chapter_number}",
                    task_type="questions",
                    book_id=book_id,
                    chapter_id=chapter_id
                )
            else:
                response = self._call_ollama_direct(prompt, force_json_format=False)
            
            questions, vocabulary, _ = self._parse_response(response, num_questions)
            
            if questions:
                logger.info(f"✓ Generated {len(questions)} questions and {len(vocabulary)} vocabulary words for {grade_level}")
                return questions, vocabulary
            else:
                logger.warning("No questions parsed from response, using fallback")
                return self._generate_fallback_questions(chapter_title, num_questions), []
                
        except Exception as e:
            logger.error(f"Question generation failed: {e}")
            logger.warning("Using fallback questions")
            return self._generate_fallback_questions(chapter_title, num_questions), []
    
    def _call_ollama_direct(self, prompt: str, force_json_format: bool = False) -> str:
        """Direct LLM API call (internal, not queued).
        
        Args:
            prompt: The prompt to send to the model
            force_json_format: If True, appends instruction for JSON
        
        Returns:
            Raw model response string
        """
        # Append JSON instruction if forced
        if force_json_format:
            prompt += "\\n\\nIMPORTANT: Respond ONLY in valid JSON format."
            
        try:
            # 1. Try Default Model (Free)
            return self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            ).choices[0].message.content

        except RateLimitError:
            # 2. Hit the limit? Switch to PAID Model
            logger.info(f"Rate limit reached for {self.model}. Switching to paid model ({settings.openrouter_paid_model})...")
            
            return self.client.chat.completions.create(
                model=settings.openrouter_paid_model,
                messages=[{"role": "user", "content": prompt}]
            ).choices[0].message.content
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    def _call_ollama(
        self, 
        prompt: str, 
        force_json_format: bool = False, 
        priority: TaskPriority = TaskPriority.QUESTION, 
        task_name: str = "",
        task_type: str = "unknown",
        book_id: Optional[str] = None,
        chapter_id: Optional[str] = None
    ) -> str:
        """Call LLM API through the priority queue.
        
        Args:
            prompt: The prompt to send to the model
            force_json_format: If True, appends instruction for JSON
            priority: Task priority level (GENRE_TAG=1, DESCRIPTION=2, QUESTION=3)
            task_name: Descriptive name for queue logging
            task_type: Type of task (description, tags, questions)
            book_id: Book/draft ID if applicable
            chapter_id: Chapter ID if applicable
        
        Returns:
            Raw model response string
        """
        try:
            return queue_ollama_call(
                func=self._call_ollama_direct,
                priority=priority,
                task_name=task_name or "llm_call",
                prompt=prompt,
                force_json_format=force_json_format,
                task_type=task_type,
                book_id=book_id,
                chapter_id=chapter_id
            )
        except Exception as e:
            logger.error(f"Queued LLM API call failed: {e}")
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
        age_range: str,
        book_id: str = None,
        use_queue: bool = True
    ) -> List[str]:
        """
        Generate tags (genre + grade level) for a book using only the title.
        
        Args:
            title: Book title
            author: Book author
            reading_level: Reading level
            age_range: Age range
            book_id: Book ID
            use_queue: If True, use queue; if False, call LLM directly
        
        Returns:
            List of tags (e.g., ["adventure", "fantasy", "grades-4-6"])
        """
        logger.info(f"Generating tags for book: {title} by {author}")
        
        # Build prompt for tag generation (using only title)
        prompt = f"""You are an expert librarian and educator analyzing children's books.

Book: "{title}" by {author}
Reading Level: {reading_level}

Based on the book title and author, provide appropriate tags:
1. Genre tags (as many as applicable, 1-4 tags): Use your best judgement to identify the most appropriate STANDARD genres based on the title and author. You MUST use standard, widely recognized genre names (e.g., "science-fiction", "biography", "folklore"). Do NOT use "cute", made-up, or non-standard tags. Keep it professional and standard.
2. Individual grade-level tags (MAXIMUM 3 GRADES): Select the 3 most likely grades from: "grade-K", "grade-1", "grade-2", "grade-3", "grade-4", "grade-5", "grade-6", "grade-7", "grade-8", "grade-9", "grade-10", "grade-11", "grade-12"
   - Include ONLY the 3 most appropriate consecutive grades for this book
   - For example, if suitable for 3rd-5th graders, include: "grade-3", "grade-4", "grade-5"
   - LIMIT: Maximum 3 grade tags total
   - STRICTLY ENFORCED: Do not provide more than 3 grade tags.

CRITICAL INSTRUCTIONS:
- Respond with ONLY valid JSON - no markdown, no code blocks, no explanations
- Return a simple array of strings
- Include 1-4 genre tags + AT MOST 3 individual grade tags (or fewer if the book has a narrower audience)
- Focus on the MOST LIKELY grades for this book based on its complexity and themes
- CRITICAL: Be accurate with grade levels. Do not assign complex books (like "Pride and Prejudice" or "Moby Dick") to lower grades. Do not assign simple picture books to high school grades.

EXACT FORMAT (copy this structure):
{{"tags":["adventure","fantasy","grade-3","grade-4","grade-5"]}}

Your entire response must be valid JSON starting with {{ and ending with }}"""
        
        # Call LLM (queue or direct based on use_queue parameter)
        try:
            if use_queue:
                response = self._call_ollama(
                    prompt, 
                    force_json_format=False,
                    priority=TaskPriority.GENRE_TAG,
                    task_name=f"generate_tags_{title}",
                    task_type="tags",
                    book_id=book_id
                )
            else:
                response = self._call_ollama_direct(prompt, force_json_format=False)
            
            tags = self._parse_tags_response(response)
            
            if tags:
                logger.info(f"✓ Generated {len(tags)} tags for book: {tags}")
                return tags
            else:
                logger.warning("No tags parsed from response, using fallback")
                return self._generate_fallback_tags(reading_level)
                
        except Exception as e:
            logger.error(f"Tag generation failed: {e}")
            logger.warning("Using fallback tags")
            return self._generate_fallback_tags(reading_level)
    
    def _parse_tags_response(self, response: str) -> List[str]:
        """Parse tags-only response from LLM.
        Works with ANY model - thinking or non-thinking."""
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
    
    def generate_synopsis(
        self,
        title: str,
        author: str,
        book_text_sample: str,
        book_id: str = None,
        use_queue: bool = True
    ) -> str:
        """
        Generate a concise synopsis from book content.
        
        Args:
            title: Book title
            author: Book author
            book_text_sample: Sample of book text (e.g., first 2000 words)
            book_id: Book ID
            use_queue: If True, use queue; if False, call LLM directly
        
        Returns:
            Generated synopsis string (max 10-12 sentences)
        """
        logger.info(f"Generating synopsis for book: {title} by {author}")
        
        # Truncate sample if too long
        words = book_text_sample.split()
        if len(words) > 2000:
            book_text_sample = ' '.join(words[:2000]) + "..."
            logger.debug(f"Truncated book sample to 2000 words")
        
        # Build prompt for synopsis generation
        prompt = f"""You are an expert librarian writing synopses for children's books.

Book: "{title}" by {author}

Here is the beginning of the book:

{book_text_sample}

Based on this excerpt, write a concise synopsis of the book (maximum 10-12 sentences).

The synopsis should:
- Summarize the main plot or themes
- Be appropriate for children
- Capture what makes the book engaging
- Be factual based on the text provided
- Be 10-12 sentences maximum
- Not use quotation marks
- Be clear and concise

CRITICAL INSTRUCTIONS:
- Respond with ONLY the synopsis text
- NO markdown, NO code blocks, NO explanations
- Just the synopsis paragraph itself
- Maximum 10-12 sentences

Your response:"""
        
        # Call LLM with retries
        max_retries = 2
        for attempt in range(max_retries):
            try:
                logger.info(f"Synopsis generation attempt {attempt + 1}/{max_retries}")
                if use_queue:
                    response = self._call_ollama(
                        prompt, 
                        force_json_format=False,
                        priority=TaskPriority.DESCRIPTION,
                        task_name=f"generate_synopsis_{title}",
                        task_type="synopsis",
                        book_id=book_id
                    )
                else:
                    response = self._call_ollama_direct(prompt, force_json_format=False)
                
                # Clean up response
                synopsis = remove_thinking_tokens(response).strip()
                
                # Remove quotes if present
                synopsis = synopsis.strip('"').strip("'")
                
                # Count sentences (rough estimate)
                sentence_count = len([s for s in synopsis.split('.') if s.strip()])
                
                # Truncate if too many sentences
                if sentence_count > 12:
                    sentences = [s.strip() + '.' for s in synopsis.split('.') if s.strip()]
                    synopsis = ' '.join(sentences[:12])
                
                # Ensure minimum length
                if len(synopsis) >= 100:
                    logger.info(f"✓ Generated synopsis ({sentence_count} sentences, {len(synopsis)} chars)")
                    return synopsis
                else:
                    logger.warning(f"Attempt {attempt + 1}: Synopsis too short ({len(synopsis)} chars)")
                
            except Exception as e:
                logger.warning(f"Synopsis attempt {attempt + 1}: {type(e).__name__} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: return a generic synopsis
        logger.warning("Using fallback synopsis")
        return f"{title} by {author} is a children's book with engaging characters and an interesting storyline."
    
    def generate_description(
        self,
        title: str,
        author: str,
        book_text_sample: str = None,
        book_id: str = None,
        use_queue: bool = True
    ) -> str:
        """
        Generate a book description, optionally auto-generating synopsis from book content.
        
        Args:
            title: Book title
            author: Book author
            book_text_sample: Optional sample of book text for auto-generating synopsis
            book_id: Book ID
            use_queue: If True, use queue; if False, call LLM directly
        
        Returns:
            Generated description string (200-500 characters)
        """
        logger.info(f"Generating description for book: {title} by {author}")
        
        # First, generate synopsis if book text sample is provided
        synopsis = None
        if book_text_sample:
            logger.info("Auto-generating synopsis from book content")
            synopsis = self.generate_synopsis(title, author, book_text_sample, book_id=book_id, use_queue=use_queue)
        
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
        
        # Call LLM with retries
        max_retries = 2
        for attempt in range(max_retries):
            try:
                logger.info(f"Description generation attempt {attempt + 1}/{max_retries}")
                if use_queue:
                    response = self._call_ollama(
                        prompt, 
                        force_json_format=False,
                        priority=TaskPriority.DESCRIPTION,
                        task_name=f"generate_description_{title}",
                        task_type="description",
                        book_id=book_id
                    )
                else:
                    response = self._call_ollama_direct(prompt, force_json_format=False)
                
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