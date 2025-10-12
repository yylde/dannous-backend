"""HTML formatting for chapter content with vocabulary annotations."""

from typing import List, Dict
import re


def format_chapter_html(
    content: str,
    vocabulary: List[Dict[str, str]],
    age_range: str,
    reading_level: str
) -> str:
    """
    Format chapter content as child-readable HTML with vocabulary annotations.
    
    Args:
        content: Raw chapter text
        vocabulary: List of vocab dicts with 'word', 'definition', 'example'
        age_range: Target age range (e.g., "8-12")
        reading_level: Reading level (beginner/intermediate/advanced)
    
    Returns:
        Formatted HTML string
    """
    # Determine font size based on age and reading level
    font_sizes = {
        'beginner': '18px',
        'intermediate': '16px',
        'advanced': '15px'
    }
    font_size = font_sizes.get(reading_level, '16px')
    
    # Start with base HTML structure
    html = f'''<div class="chapter-content" style="
        font-family: 'Georgia', 'Times New Roman', serif;
        font-size: {font_size};
        line-height: 1.8;
        color: #2d3748;
        max-width: 800px;
        margin: 0 auto;
        padding: 20px;
    ">'''
    
    # Split content into paragraphs
    paragraphs = content.split('\n\n')
    
    for para in paragraphs:
        if not para.strip():
            continue
            
        # Apply vocabulary annotations
        annotated_para = apply_vocabulary_annotations(para, vocabulary)
        
        html += f'<p style="margin-bottom: 1.5em; text-indent: 2em;">{annotated_para}</p>'
    
    html += '</div>'
    
    return html


def apply_vocabulary_annotations(text: str, vocabulary: List[Dict[str, str]]) -> str:
    """
    Replace vocabulary words with <abbr> tags containing definitions.
    
    Args:
        text: Text paragraph
        vocabulary: List of vocab dicts
    
    Returns:
        Text with <abbr> annotations
    """
    result = text
    
    # Sort by word length (longest first) to avoid partial replacements
    sorted_vocab = sorted(vocabulary, key=lambda x: len(x['word']), reverse=True)
    
    for vocab in sorted_vocab:
        word = vocab['word']
        definition = vocab['definition']
        example = vocab.get('example', '')
        
        # Create tooltip text
        tooltip = f"{definition}"
        if example:
            tooltip += f" Example: {example}"
        
        # Escape special regex characters
        escaped_word = re.escape(word)
        
        # Replace whole word matches (case-insensitive)
        # Use word boundaries to avoid partial matches
        pattern = r'\b(' + escaped_word + r')\b'
        replacement = f'<abbr title="{tooltip}" style="text-decoration: underline dotted #667eea; cursor: help;">\\1</abbr>'
        
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result