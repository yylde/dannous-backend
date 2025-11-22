
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from openai import RateLimitError

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

# Mock settings and queue to avoid import errors if they depend on other things
mock_settings = MagicMock()
mock_settings.openrouter_free_model = "x-ai/grok-4.1-fast:free"
mock_settings.openrouter_paid_model = "google/gemini-flash-1.5"
mock_settings.openrouter_api_key = "dummy_key"

with patch.dict(sys.modules, {'src.config': MagicMock(settings=mock_settings), 'src.ollama_queue': MagicMock()}):
    from src.question_generator import QuestionGenerator

class TestQuestionGenerator(unittest.TestCase):
    def setUp(self):
        self.qg = QuestionGenerator()
        # Mock the client
        self.qg.client = MagicMock()

    def test_direct_call_success(self):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Success Response"
        self.qg.client.chat.completions.create.return_value = mock_response

        response = self.qg._call_ollama_direct("Test Prompt")
        
        self.assertEqual(response, "Success Response")
        # Verify default model was used and NO extra headers
        self.qg.client.chat.completions.create.assert_called_with(
            model="x-ai/grok-4.1-fast:free",
            messages=[{"role": "user", "content": "Test Prompt"}]
        )

    def test_rate_limit_fallback(self):
        # Setup mock to raise RateLimitError first, then return success
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Fallback Response"
        
        def side_effect(*args, **kwargs):
            if kwargs['model'] == "x-ai/grok-4.1-fast:free":
                raise RateLimitError(message="Rate limit reached", response=MagicMock(), body=None)
            return mock_response

        self.qg.client.chat.completions.create.side_effect = side_effect

        response = self.qg._call_ollama_direct("Test Prompt")
        
        self.assertEqual(response, "Fallback Response")
        # Verify fallback model was used and NO extra headers
        self.qg.client.chat.completions.create.assert_called_with(
            model="google/gemini-flash-1.5",
            messages=[{"role": "user", "content": "Test Prompt"}]
        )

if __name__ == '__main__':
    unittest.main()
