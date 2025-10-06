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
        
        # Safety check: if we removed more than 90% of content, something went wrong
        if self.cleaned_length < (self.original_length * 0.1):
            logger.warning(
                f"⚠️  Cleaning removed {removed} words ({removed/self.original_length*100:.1f}%), "
                f"which seems excessive. Using original text instead."
            )
            return text  # Return what we have, don't use original to avoid PG boilerplate
        
        logger.info(f"Removed {removed} words of boilerplate ({removed/self.original_length*100:.1f}%)")
        
        return text
    
    def _remove_header(self, text: str) -> str:
        """Remove Project Gutenberg header/preamble."""
        for pattern in self.PG_START_MARKERS:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                # Keep everything after the marker
                start_pos = match.end()
                # Skip any remaining blank lines after the marker
                remaining = text[start_pos:].lstrip('\n')
                logger.debug(f"Removed header (kept {len(remaining.split())} words)")
                return remaining
        
        logger.debug("No header marker found")
        return text
    
    def _remove_footer(self, text: str) -> str:
        """Remove Project Gutenberg footer/postamble."""
        for pattern in self.PG_END_MARKERS:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                # Keep everything before the marker
                end_pos = match.start()
                result = text[:end_pos].rstrip('\n')
                logger.debug(f"Removed footer (kept {len(result.split())} words)")
                return result
        
        logger.debug("No footer marker found")
        return text
    
    def _remove_license_sections(self, text: str) -> str:
        """Remove embedded license and footer text."""
        lines = text.split('\n')
        cleaned_lines = []
        skip_mode = False
        
        for line in lines:
            # Check if line contains license/footer markers
            is_license_line = False
            for pattern in self.PG_FOOTER_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    is_license_line = True
                    break
            
            # Skip license lines but keep narrative content
            if is_license_line:
                skip_mode = True
                continue
            
            # If we hit a blank line after license content, stop skipping
            if skip_mode and line.strip() == '':
                skip_mode = False
                continue
            
            # Keep the line if not in skip mode
            if not skip_mode:
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
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