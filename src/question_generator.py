"""Question generation using Ollama LLM."""

import json
import logging
import time
from typing import List, Dict
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

For each question, provide 3-5 expected keywords that would appear in a good answer.

Respond ONLY with valid JSON in this exact format (no markdown, no code blocks):
{{
  "questions": [
    {{
      "text": "Why did [character/event]...",
      "keywords": ["keyword1", "keyword2", "keyword3"],
      "difficulty": "medium"
    }}
  ]
}}"""
    
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
    ) -> List[Dict[str, any]]:
        """Generate questions for a chapter."""
        if num_questions is None:
            num_questions = settings.questions_per_chapter
        
        logger.info(
            f"Generating {num_questions} questions for "
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
                questions = self._parse_response(response, num_questions)
                
                if questions:
                    logger.info(f"✓ Generated {len(questions)} questions")
                    return questions
                
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        # Fallback: generate generic questions
        logger.warning("Using fallback questions")
        return self._generate_fallback_questions(chapter_title, num_questions)
    
    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API."""
        try:
            response = ollama.generate(
                model=self.model,
                prompt=prompt,
                options={
                    'temperature': 0.7,
                    'top_p': 0.9,
                }
            )
            return response['response']
        except Exception as e:
            logger.error(f"Ollama API call failed: {e}")
            raise
    
    def _parse_response(self, response: str, expected_count: int) -> List[Dict]:
        """Parse JSON response from LLM."""
        try:
            # Remove markdown code blocks if present
            response = response.strip()
            if response.startswith('```'):
                response = response.split('```')[1]
                if response.startswith('json'):
                    response = response[4:]
            
            # Parse JSON
            data = json.loads(response)
            
            if 'questions' not in data:
                raise ValueError("No 'questions' key in response")
            
            questions = []
            for i, q in enumerate(data['questions'][:expected_count]):
                # Validate question structure
                if 'text' not in q:
                    logger.warning(f"Question {i} missing 'text' field")
                    continue
                
                questions.append({
                    'text': q['text'].strip(),
                    'keywords': q.get('keywords', []),
                    'difficulty': q.get('difficulty', 'medium')
                })
            
            return questions
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Response was: {response[:200]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return []
    
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


def save_prompt_template(filepath: str = "prompts/question_generation.txt"):
    """Save the prompt template to a file for documentation."""
    import os
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    generator = QuestionGenerator()
    with open(filepath, 'w') as f:
        f.write(generator.prompt_template)
    
    logger.info(f"Saved prompt template to {filepath}")