"""Question generation using OpenRouter LLM."""

import json
import logging
import re
import time
import os
from typing import List, Dict, Tuple, Optional, Any
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
    def _clean_and_parse_json(self, response: str) -> Any:
        """
        Robustly clean and parse JSON from LLM response.
        Handles thinking tokens, markdown blocks, and finding JSON objects/arrays.
        """
        try:
            # Remove thinking tokens
            response = remove_thinking_tokens(response)
            response = response.strip()
            
            # Remove markdown code blocks
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0].strip()
            elif '```' in response:
                parts = response.split('```')
                for part in parts:
                    part = part.strip()
                    if (part.startswith('{') and part.endswith('}')) or \
                       (part.startswith('[') and part.endswith(']')):
                        response = part
                        break
            
            # Try to find JSON structure using regex
            # Matches both objects {} and arrays []
            # This regex attempts to match balanced braces/brackets to some extent
            json_pattern = r'(\{.*\}|\[.*\])'
            json_matches = re.findall(json_pattern, response, re.DOTALL)
            
            if json_matches:
                # Take the longest match
                candidate = max(json_matches, key=len)
                try:
                    return json.loads(candidate)
                except:
                    pass # Regex match failed to parse, try manual fallback
            
            # Fallback: manual boundary finding
            # Try to find the outer-most JSON object or array
            for start_char, end_char in [('{', '}'), ('[', ']')]:
                if start_char in response:
                    start_idx = response.find(start_char)
                    end_idx = response.rfind(end_char)
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        candidate = response[start_idx:end_idx+1]
                        try:
                            return json.loads(candidate)
                        except:
                            continue

            # Last attempt: parse the whole string
            return json.loads(response)
            
        except Exception as e:
            logger.error(f"Error parsing JSON: {e}")
            logger.debug(f"Failed response content: {response[:500]}")
            return None

    def analyze_content_safety(self, book_text: str, grade_level: str) -> List[Dict]:
        """
        Analyze book content for controversial items based on grade level.
        
        Args:
            book_text: Full text of the book
            grade_level: Target grade level string
            
        Returns:
            List of dictionaries containing safety flags/issues
        """
        logger.info(f"Analyzing content safety for grade level: {grade_level}")
        
        prompt = f"""You are an expert content moderator and educational consultant. Your task is to review the following book content for items that may be controversial, offensive, or inappropriate for students in {grade_level}.

Flag any of the following issues (be STRICT and flag even minor instances):

1. Racial and Ethnic Stereotypes (CRITICAL)
   - The "Savage" Trope: Depicting Indigenous or non-white people as violent, primitive, or animalistic.
   - Dehumanization: Treating non-white characters as less than human (e.g., "Blacks are not people").
   - Dialect: Exaggerated phonetic spelling to mock speech of Black or working-class characters.
   - Anti-Semitism: Greedy or villainous Jewish caricatures.
   - Slurs: Casual use of terms like "N-word", "Injun", "Gypsy", "Chinaman", "Heathen", "Piccaninny", "Redskins", "Blacks" (as a noun).
   - Negative comparisons involving skin color (e.g., "washing black white").

2. Colonialism and Imperialism
   - White Saviorism: White protagonist instantly ruling or "fixing" foreign cultures.
   - Dehumanization: Local populations treated as background scenery, wildlife, or solely to serve white people.
   - "White man's burden" narratives: Becoming "better" or "healthier" by shedding non-white cultural influences.

3. Outdated Safety and Medical Advice / Ableism
   - Dangerous Play: Unsupervised play with explosives, firearms, or dangerous machinery.
   - Harmful "Cures": Mercury, bleeding, or strange home remedies.
   - Disability as "Moral Failing": Implying disability is a choice, a result of a "bad attitude", or cured by "believing hard enough" (e.g., "fresh air cure" for paralysis).
   - The "Magic Cure" Trope: Suggesting physical disabilities are psychosomatic or can be wished away.

4. Violence, Horror, and Grim Themes
   - Gore and Mutilation: Explicit descriptions of physical harm.
   - Cruelty to Animals: Graphically depicted violence against animals (e.g., shooting dogs, hurting pets).
   - Grim Death/Neglect: Blunt descriptions of death, corpses, or severe parental neglect (e.g., children left alone with dead bodies).

5. Sexism and Gender Roles
   - Lack of Agency: Female characters existing only to be rescued or serve men.
   - Domestic Servitude: Girls cooking/cleaning while boys adventure.
   - "Taming" Narratives: Tomboyish girls punished until they become "proper ladies".

6. Classism and Social Stigma
   - Mocking the Poor: Depicting poor characters as lazy, dirty, or stupid.
   - Servant Mistreatment: Abusive language towards servants presented as normal or acceptable.
   - Caricatured Dialect: "Simple" or difficult-to-read dialect for working-class characters.

For each issue found, provide a structured response in JSON format.
CRITICAL INSTRUCTIONS:
1. BE EXHAUSTIVE: Flag EVERY single instance of the issues listed above. Do not skip any. If in doubt, FLAG IT.
2. STRICT CHRONOLOGICAL ORDER: List issues EXACTLY in the order they appear in the text. Do not reorder based on chapter numbers.
3. LOCATION: Use whatever chapter header (Roman numeral, number, or title) is nearest to the issue. If no header is clear, use "Text Segment".
4. SEPARATE ENTRIES: If the same issue appears 10 times, create 10 separate entries.

The response should be a JSON object with a single key "issues" containing a list of objects.
Each object should have the following fields:
- "issue": A short title for the issue (e.g., "The Racial Slur 'Gypsy'").
- "location": The specific chapter/section where this instance appears.
- "context": A brief description of the scene or context for this specific instance.
- "explanation": Why this is an issue.
- "original_text": The specific snippet of text causing the issue.
- "rewrite": A suggested rewrite to make it appropriate, or "FLAG_ONLY" if it cannot be easily rewritten.

Example Output Format:
{{
    "issues": [
        {{
            "issue": "The Racial Slur 'Gypsy'",
            "location": "Chapter I",
            "context": "Introduction of the character.",
            "explanation": "Offensive exonym.",
            "original_text": "The old gypsy woman...",
            "rewrite": "The old traveler woman..."
        }},
        {{
            "issue": "Violence against Animals",
            "location": "The Hunting Scene",
            "context": "A dog is kicked by the antagonist.",
            "explanation": "Cruelty to animals.",
            "original_text": "He kicked the poor hound...",
            "rewrite": "FLAG_ONLY"
        }}
    ]
}}

If no issues are found, return: {{ "issues": [] }}

Book Content:
{book_text[:1000000]} 
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful educational content safety assistant. Output ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # Zero temperature for maximum determinism
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            
            # Use robust parsing helper
            data = self._clean_and_parse_json(content)
            
            if not data:
                error_msg = f"Failed to parse JSON from safety check response: {content[:100]}..."
                logger.error(error_msg)
                raise ValueError(error_msg)
                
            if isinstance(data, dict):
                # Look for likely keys
                for key in ['issues', 'flags', 'items', 'results']:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                # If no list found, maybe the dict itself is a single item?
                # But we expect a list wrapper now.
                return []
            elif isinstance(data, list):
                # Should not happen with json_object prompt, but handle it
                return data
                
            return []
                
        except Exception as e:
            logger.error(f"Error in content safety analysis: {e}")
            raise e  # Re-raise exception to trigger queue error handling
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
        book_text: str = None,
        book_id: str = None,
        use_queue: bool = True
    ) -> str:
        """
        Generate a book description from the full book text.
        
        Args:
            title: Book title
            author: Book author
            book_text: Full book text (plain text without HTML)
            book_id: Book ID
            use_queue: If True, use queue; if False, call LLM directly
        
        Returns:
            Generated description string (3-4 sentences)
        """
        logger.info(f"Generating description for book: {title} by {author}")
        
        # Truncate book text if too long (to avoid context limits)
        # Use more text than synopsis since we want a better understanding
        if book_text and len(book_text) > 100000:
            book_text = book_text[:100000] + "..."
            logger.debug(f"Truncated book text to 100k characters")
        
        # Build prompt for description generation
        book_content = f"\n\nBook Content:\n{book_text}" if book_text else ""
        
        prompt = f"""You are a professional book marketer writing compelling back-cover descriptions that sound sophisticated and enticing.

Book: "{title}" by {author}{book_content}

Based on the book content above, write a DESCRIPTIVE, THEMATIC book description (3-5 sentences).

CRITICAL - Write like a REAL book description:
✅ Start with thematic framing: "A thrilling adventure about...", "A heartwarming tale of...", "An exciting story about...", "A charming adventure featuring..."
✅ Use RICH, DESCRIPTIVE language - not simple choppy sentences
✅ Paint a vivid picture of the world and characters
✅ Explain what kind of story this is (adventure, mystery, comedy, etc.)
✅ Give enough detail so readers understand the premise and conflict
✅ Build narrative flow from setup → conflict → stakes
✅ End with the central question/challenge without revealing the resolution

The description should:
- Be 3-5 sentences with sophisticated, flowing prose
- Open with thematic framing that describes what KIND of story this is
- Match the tone to the book's target age group (warm for young kids, sophisticated for older readers/YA)
- Use RICH, VIVID, DESCRIPTIVE language - avoid childish or choppy writing
- Introduce characters with personality and context
- Explain the situation, conflict, and what's at stake
- Provide enough information so readers clearly understand what the book is about
- Build to an unresolved question or challenge
- NO SPOILERS about how conflicts resolve or how the story ends
- Sound professional and enticing, like descriptions from major publishers

Think: "How would a professional publisher describe this book to make it sound irresistible?"

Examples of GOOD, DESCRIPTIVE book descriptions:

✅ "A delightful tale of mischief and danger in the English countryside. The Flopsy Bunnies discover a treasure trove of overgrown lettuces at Mr. McGregor's rubbish heap, but their feast sends them into a deep sleep right in enemy territory. When the grumpy farmer stumbles upon the slumbering rabbits, only clever Benjamin Bunny stands between his family and disaster."

✅ "A classic adventure of disobedience, danger, and daring escape. Young Peter Rabbit knows the rules - stay out of Mr. McGregor's garden, where his father met a terrible fate. But when the lure of fresh vegetables proves too strong, Peter finds himself in a wild chase that will test all his courage and cleverness."

✅ "An imaginative journey into a world of wonder and whimsy. Bored on a drowsy afternoon, young Alice follows a peculiar white rabbit down a mysterious hole and tumbles into Wonderland - a place where logic has no meaning and the impossible happens constantly. When she encounters the terrifying Queen of Hearts, Alice realizes that finding her way home may be the greatest challenge of all."

CRITICAL INSTRUCTIONS:
- Respond with ONLY the description text
- NO markdown, NO code blocks, NO explanations
- Write with sophisticated, descriptive prose
- Make it sound professional and enticing
- 3-5 sentences that flow beautifully

Your response:"""
        
        # Call LLM with retries - Use queue with HARDCODED Gemini 2.0 Flash for descriptions
        max_retries = 2
        description_model = "x-ai/grok-4.1-fast:free"
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Description generation attempt {attempt + 1}/{max_retries} using {description_model}")
                
                if use_queue:
                    # Use queue but with hardcoded Gemini 2.0 Flash model
                    response = self._call_ollama_with_model(
                        prompt=prompt,
                        model=description_model,
                        force_json_format=False,
                        priority=TaskPriority.DESCRIPTION,
                        task_name=f"generate_description_{title}",
                        task_type="description",
                        book_id=book_id
                    )
                else:
                    # Direct call with Gemini 2.0 Flash
                    response = self.client.chat.completions.create(
                        model=description_model,
                        messages=[{"role": "user", "content": prompt}]
                    ).choices[0].message.content
                
                # Clean up response
                description = remove_thinking_tokens(response).strip()
                
                # Remove quotes if present
                description = description.strip('"').strip("'")
                
                # Count sentences
                sentence_count = len([s for s in description.split('.') if s.strip()])
                
                # Validate sentence count (3-5 sentences)
                if 3 <= sentence_count <= 5:
                    logger.info(f"✓ Generated description ({sentence_count} sentences): {description[:100]}...")
                    return description
                else:
                    logger.warning(f"Attempt {attempt + 1}: Description has {sentence_count} sentences (need 3-5), retrying...")
                    continue
                
            except Exception as e:
                logger.warning(f"Description attempt {attempt + 1}: {type(e).__name__} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: return a generic description
        logger.warning("Using fallback description")
        return f"{title} by {author} is a captivating children's book that engages young readers with its compelling story and memorable characters."
    
    def _call_ollama_with_model(
        self, 
        prompt: str,
        model: str,
        force_json_format: bool = False, 
        priority: TaskPriority = TaskPriority.DESCRIPTION, 
        task_name: str = "",
        task_type: str = "unknown",
        book_id: Optional[str] = None,
        chapter_id: Optional[str] = None
    ) -> str:
        """Call LLM API through the priority queue with a specific model.
        
        Args:
            prompt: The prompt to send to the model
            model: Specific model to use (overrides self.model)
            force_json_format: If True, appends instruction for JSON
            priority: Task priority level
            task_name: Descriptive name for queue logging
            task_type: Type of task (description, tags, questions)
            book_id: Book/draft ID if applicable
            chapter_id: Chapter ID if applicable
        
        Returns:
            Raw model response string
        """
        try:
            # Create a custom function that uses the specified model
            def call_with_custom_model(prompt: str, force_json_format: bool = False) -> str:
                if force_json_format:
                    prompt += "\\n\\nIMPORTANT: Respond ONLY in valid JSON format."
                
                try:
                    return self.client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}]
                    ).choices[0].message.content
                except Exception as e:
                    logger.error(f"LLM call failed with model {model}: {e}")
                    raise
            
            return queue_ollama_call(
                func=call_with_custom_model,
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