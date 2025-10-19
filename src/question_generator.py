"""Question generation using Ollama LLM."""

import json
import logging
import time
from typing import List, Dict, Tuple
import ollama
from .config import settings

logger = logging.getLogger(__name__)


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
        """Load question generation prompt template."""
        return """You are an expert educator creating reading comprehension questions for children.

Book: "{title}" by {author}
Chapter {chapter_number}: {chapter_title}
Reading Level: {reading_level}
Age Range: {age_range}

Chapter Text:
{chapter_text}

Generate exactly {num_questions} open-ended comprehension questions that:
1. Are NOT multiple choice or yes/no questions
2. Start with "Why" or "How" to encourage critical thinking
3. Require {min_words}-{max_words} word thoughtful answers
4. Test understanding beyond simple recall
5. Are appropriate for {age_range} year old children
6. Focus on themes, character motivation, cause-and-effect, or inference

Additionally, identify 5-8 words that might be difficult for a child at reading level "{reading_level}" and age range "{age_range}". For each word, provide:
- word: the difficult word (must appear in the chapter text)
- definition: a child-friendly definition
- example: a simple example sentence using the word in context

CRITICAL INSTRUCTIONS:
- Respond with ONLY valid JSON - no markdown, no code blocks, no explanations
- DO NOT nest "questions" arrays inside questions - keep it flat
- Each question must have: "text", "keywords" (array), "difficulty"
- Each vocabulary item must have: "word", "definition", "example"

Additionally, analyze the text and provide:
- Genre tags (e.g., "adventure", "fantasy", "mystery", "historical-fiction", "science-fiction", "realistic-fiction")
- Grade-appropriate tags based on content complexity (e.g., "grades-1-3", "grades-4-6", "grades-7-9", "grades-10-12")
- Select 2-4 tags total that best describe the content

EXACT FORMAT (copy this structure):
{{"questions":[{{"text":"Why did the character...","keywords":["character","action"],"difficulty":"medium"}},{{"text":"How does the setting...","keywords":["setting","mood"],"difficulty":"easy"}}],"vocabulary":[{{"word":"example","definition":"simple meaning","example":"Sample sentence using example."}}],"tags":["adventure","fantasy","grades-4-6"]}}

Your entire response must be valid JSON starting with {{ and ending with }}"""

    def _parse_response(self, response: str, expected_count: int) -> Tuple[List[Dict], List[Dict], List[str]]:
        """
        Parse JSON response from LLM with robust error handling.
        
        Returns:
            Tuple of (questions, vocabulary, tags)
        """
        try:
            # Clean up response
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
            
            # Try to find JSON object if wrapped in text
            if not response.startswith('{'):
                start_idx = response.find('{')
                if start_idx != -1:
                    response = response[start_idx:]
            
            if not response.endswith('}'):
                end_idx = response.rfind('}')
                if end_idx != -1:
                    response = response[:end_idx + 1]
            
            # Parse JSON
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
        num_questions: int = None
    ) -> Tuple[List[Dict[str, any]], List[Dict[str, str]], List[str]]:
        """
        Generate questions, vocabulary, and tags for a chapter.
        
        Returns:
            Tuple of (questions_list, vocabulary_list, tags_list)
        """
        if num_questions is None:
            num_questions = settings.questions_per_chapter
        
        logger.info(
            f"Generating {num_questions} questions and vocabulary for "
            f"Chapter {chapter_number}: {chapter_title}"
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
            num_questions=num_questions,
            min_words=settings.min_answer_words,
            max_words=settings.max_answer_words
        )
        
        # Call Ollama with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self._call_ollama(prompt)
                questions, vocabulary, tags = self._parse_response(response, num_questions)
                
                if questions:
                    logger.info(f"✓ Generated {len(questions)} questions, {len(vocabulary)} vocabulary words, and {len(tags)} tags")
                    return questions, vocabulary, tags
                
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        # Fallback: generate generic questions, empty vocabulary, and empty tags
        logger.warning("Using fallback questions")
        return self._generate_fallback_questions(chapter_title, num_questions), [], []
    
    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API with improved settings."""
        try:
            response = ollama.generate(
                model=self.model,
                prompt=prompt,
                options={
                    'temperature': 0.7,
                    'top_p': 0.9,
                    'hidethinking': True,
                    'num_predict': 4000, 
                     "think": False # Ensure enough tokens for response
                },
                format='json'  # Request JSON format
            )
            print(response['response'])
            return response['response']
        except Exception as e:
            logger.error(f"Ollama API call failed: {e}")
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
        book_text: str,
        reading_level: str,
        age_range: str
    ) -> List[str]:
        """
        Generate tags (genre + grade level) for an entire book.
        
        Args:
            title: Book title
            author: Book author
            book_text: Full book text or sample
            reading_level: Reading level
            age_range: Age range
        
        Returns:
            List of tags (e.g., ["adventure", "fantasy", "grades-4-6"])
        """
        logger.info(f"Generating tags for book: {title} by {author}")
        
        # Take a sample from the beginning and middle of the book (max 3000 words)
        words = book_text.split()
        sample_size = min(3000, len(words))
        
        # Take 60% from beginning, 40% from middle
        beginning_size = int(sample_size * 0.6)
        middle_start = len(words) // 2
        middle_size = sample_size - beginning_size
        
        beginning_text = ' '.join(words[:beginning_size])
        middle_text = ' '.join(words[middle_start:middle_start + middle_size])
        sample_text = beginning_text + '\n\n[...]\n\n' + middle_text
        
        # Build prompt for tag generation
        prompt = f"""You are an expert librarian and educator analyzing children's books.

Book: "{title}" by {author}
Reading Level: {reading_level}
Age Range: {age_range}

Book Sample:
{sample_text}

Analyze this book and provide appropriate tags:
1. Genre tags (2-3 tags): Select from: "adventure", "fantasy", "mystery", "historical-fiction", "science-fiction", "realistic-fiction", "humor", "horror", "romance", "poetry", "biography", "educational"
2. Grade-level tags (1 tag): Select from: "grades-K-2", "grades-1-3", "grades-4-6", "grades-7-9", "grades-10-12"

CRITICAL INSTRUCTIONS:
- Respond with ONLY valid JSON - no markdown, no code blocks, no explanations
- Return a simple array of strings
- Select 3-5 tags total

EXACT FORMAT (copy this structure):
{{"tags":["adventure","fantasy","grades-4-6"]}}

Your entire response must be valid JSON starting with {{ and ending with }}"""
        
        # Call Ollama with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self._call_ollama(prompt)
                tags = self._parse_tags_response(response)
                
                if tags:
                    logger.info(f"✓ Generated {len(tags)} tags for book: {tags}")
                    return tags
                
            except Exception as e:
                logger.warning(f"Tag generation attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # Fallback: return generic tags based on reading level
        logger.warning("Using fallback tags")
        return self._generate_fallback_tags(reading_level)
    
    def _parse_tags_response(self, response: str) -> List[str]:
        """Parse tags-only response from LLM."""
        try:
            # Clean up response
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
            
            # Try to find JSON object
            if not response.startswith('{'):
                start_idx = response.find('{')
                if start_idx != -1:
                    response = response[start_idx:]
            
            if not response.endswith('}'):
                end_idx = response.rfind('}')
                if end_idx != -1:
                    response = response[:end_idx + 1]
            
            # Parse JSON
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
    
    def _generate_fallback_tags(self, reading_level: str) -> List[str]:
        """Generate fallback tags based on reading level."""
        # Map reading level to grade tags
        level_map = {
            'beginner': 'grades-K-2',
            'early-reader': 'grades-1-3',
            'intermediate': 'grades-4-6',
            'advanced': 'grades-7-9',
            'young-adult': 'grades-10-12'
        }
        
        grade_tag = level_map.get(reading_level, 'grades-4-6')
        return ['fiction', grade_tag]


def save_prompt_template(filepath: str = "prompts/question_generation.txt"):
    """Save the prompt template to a file for documentation."""
    import os
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    generator = QuestionGenerator()
    with open(filepath, 'w') as f:
        f.write(generator.prompt_template)
    
    logger.info(f"Saved prompt template to {filepath}")