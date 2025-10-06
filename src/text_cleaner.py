"""Text cleaning and Project Gutenberg boilerplate removal."""

import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class TextCleaner:
    """Clean and sanitize text content."""
    
    # Project Gutenberg start markers
    PG_START_MARKERS = [
        r'\*\*\* START OF (THIS|THE) PROJECT GUTENBERG EBOOK .+? \*\*\*',
        r'START OF (THIS|THE) PROJECT GUTENBERG EBOOK',
        r'\*\*\*START OF THE PROJECT GUTENBERG EBOOK',
        r'The Project Gutenberg eBook of .+?, by',
    ]
    
    # Project Gutenberg end markers
    PG_END_MARKERS = [
        r'\*\*\* END OF (THIS|THE) PROJECT GUTENBERG EBOOK .+? \*\*\*',
        r'END OF (THIS|THE) PROJECT GUTENBERG EBOOK',
        r'\*\*\*END OF THE PROJECT GUTENBERG EBOOK',
        r'End of (the )?Project Gutenberg',
    ]
    
    # License/footer patterns to remove
    PG_FOOTER_PATTERNS = [
        r'Project Gutenberg.{0,50}(License|Terms|Conditions)',
        r'Section \d+\..+?Information about.+?Project Gutenberg',
        r'Please check the Project Gutenberg.+?pages',
        r'donations? (are|is) gratefully accepted',
        r'www\.gutenberg\.(org|net)',
        r'Most people start at our (Web site|website)',
        r'Information about (Donations|the Mission)',
        r'HOW TO DONATE',
        r'Literary Archive Foundation',
        r'INDEMNITY.*?direct or indirect',
        r'This (Web site|website) includes information about Project Gutenberg',
    ]
    
    def __init__(self):
        """Initialize text cleaner."""
        self.original_length = 0
        self.cleaned_length = 0
    
    def clean(self, text: str) -> str:
        """Clean text by removing Project Gutenberg boilerplate."""
        self.original_length = len(text.split())
        logger.info(f"Cleaning text ({self.original_length} words)...")
        
        # Remove PG header
        text = self._remove_header(text)
        
        # Remove PG footer
        text = self._remove_footer(text)
        
        # Remove license sections
        text = self._remove_license_sections(text)
        
        # Normalize whitespace
        text = self._normalize_whitespace(text)
        
        self.cleaned_length = len(text.split())
        removed = self.original_length - self.cleaned_length
        logger.info(f"Removed {removed} words of boilerplate")
        
        return text
    
    def _remove_header(self, text: str) -> str:
        """Remove Project Gutenberg header/preamble."""
        for pattern in self.PG_START_MARKERS:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                # Keep everything after the marker
                start_pos = match.end()
                text = text[start_pos:]
                logger.debug(f"Removed header at position {start_pos}")
                break
        
        return text
    
    def _remove_footer(self, text: str) -> str:
        """Remove Project Gutenberg footer/postamble."""
        for pattern in self.PG_END_MARKERS:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                # Keep everything before the marker
                end_pos = match.start()
                text = text[:end_pos]
                logger.debug(f"Removed footer at position {end_pos}")
                break
        
        return text
    
    def _remove_license_sections(self, text: str) -> str:
        """Remove embedded license and footer text."""
        for pattern in self.PG_FOOTER_PATTERNS:
            # Remove entire paragraphs containing these patterns
            text = re.sub(
                r'[^\n]*' + pattern + r'[^\n]*\n?',
                '',
                text,
                flags=re.IGNORECASE | re.DOTALL
            )
        
        return text
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace while preserving paragraph breaks."""
        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)
        
        # Replace more than 2 newlines with 2 newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove leading/trailing whitespace from lines
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines)
        
        return text.strip()
    
    def get_cleaning_stats(self) -> Tuple[int, int, int]:
        """Get cleaning statistics."""
        removed = self.original_length - self.cleaned_length
        return self.original_length, self.cleaned_length, removed


def extract_description(text: str, max_length: int = 500) -> str:
    """Extract a description from the beginning of the text."""
    # Take first few paragraphs
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    description = ""
    for para in paragraphs[:3]:
        # Skip very short paragraphs (likely headings)
        if len(para) < 50:
            continue
        
        description = para
        break
    
    # Truncate to max length
    if len(description) > max_length:
        description = description[:max_length].rsplit(' ', 1)[0] + '...'
    
    return description or "No description available."