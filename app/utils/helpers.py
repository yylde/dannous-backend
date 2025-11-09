"""Utility helper functions for text processing."""

import re


def split_into_pages(text, words_per_page=500):
    """Split text into pages for easier navigation, preserving paragraph structure."""
    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
    pages = []
    current_page = []
    current_word_count = 0
    
    for para in paragraphs:
        para_words = len(para.split())
        
        if current_word_count + para_words > words_per_page and current_page:
            pages.append('\n\n'.join(current_page))
            current_page = [para]
            current_word_count = para_words
        else:
            current_page.append(para)
            current_word_count += para_words
    
    if current_page:
        pages.append('\n\n'.join(current_page))
    
    return pages if pages else [text]


def extract_description(text, max_length=500):
    """Extract description from text."""
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    for para in paragraphs[:3]:
        if len(para) >= 50:
            description = para
            if len(description) > max_length:
                description = description[:max_length].rsplit(' ', 1)[0] + '...'
            return description
    
    return "No description available."
