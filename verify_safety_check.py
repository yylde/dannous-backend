
import os
import sys
import json
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.queue_executors import execute_safety_check

def test_execute_safety_check():
    print("Testing execute_safety_check...")
    
    # Mock the OpenAI client
    with patch('src.question_generator.OpenAI') as mock_openai:
        # Setup mock response
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps([
            {
                "issue": "The Racial Slur 'Gypsy'",
                "location": "Chapter XII",
                "context": "The 'Gypsy Supper' scene.",
                "explanation": "This is an offensive exonym for the Romani people.",
                "original_text": "Miss Grace Clifford... invited to a gypsy supper in the Pines.",
                "rewrite": "Miss Grace Clifford... invited to a campfire supper in the Pines."
            }
        ])
        mock_client.chat.completions.create.return_value = mock_response
        
        # Test input with HTML and Gutenberg markers
        book_id = "test-draft-id"
        book_text = """
        *** START OF THE PROJECT GUTENBERG EBOOK TEST ***
        <p>Actual content with <b>HTML</b>.</p>
        *** END OF THE PROJECT GUTENBERG EBOOK TEST ***
        """
        grade_level = "4th-6th Grade"
        
        # Run execution
        with patch('src.queue_executors.DatabaseManager') as MockDB:
            mock_db = MockDB.return_value
            
            # We want to verify that analyze_content_safety receives the CLEANED text
            # So we spy on the generator instance
            with patch('src.queue_executors.QuestionGenerator') as MockGen:
                mock_gen_instance = MockGen.return_value
                mock_gen_instance.analyze_content_safety.return_value = [
                    {"issue": "The Racial Slur 'Gypsy'", "rewrite": "Fix"}
                ]
                
                results = execute_safety_check(book_id, book_text, grade_level)
                
                # Check what was passed to analyze_content_safety
                args, _ = mock_gen_instance.analyze_content_safety.call_args
                cleaned_text_arg = args[0]
                
                print(f"Cleaned Text passed to LLM: '{cleaned_text_arg}'")
                
                if "*** START" not in cleaned_text_arg and "Actual content with HTML" in cleaned_text_arg:
                     print("✓ Verification SUCCESS: Gutenberg headers stripped and HTML removed")
                else:
                     print(f"✗ Verification FAILED: Text not cleaned properly. Got: {cleaned_text_arg}")

if __name__ == "__main__":
    test_execute_safety_check()
