"""EPUB file parsing and text extraction."""

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
import logging
import re

logger = logging.getLogger(__name__)


class EPUBParser:
    """Parse EPUB files and extract text content."""
    
    def __init__(self, filepath: str):
        """Initialize parser with EPUB file path."""
        self.filepath = filepath
        self.book = None
        self.metadata = {}
        self.chapters_raw = []
    
    def parse(self) -> Dict:
        """Parse EPUB file and extract all content."""
        logger.info(f"Parsing EPUB: {self.filepath}")
        
        try:
            # Read EPUB file
            self.book = epub.read_epub(self.filepath)
            
            # Extract metadata
            self.metadata = self._extract_metadata()
            
            # Extract text content
            self.chapters_raw = self._extract_text()
            
            logger.info(
                f"Extracted {len(self.chapters_raw)} sections, "
                f"~{sum(len(c.split()) for c in self.chapters_raw)} words"
            )
            
            return {
                "metadata": self.metadata,
                "raw_text": "\n\n".join(self.chapters_raw),
                "sections": self.chapters_raw
            }
            
        except Exception as e:
            logger.error(f"Failed to parse EPUB: {e}")
            raise
    
    def _extract_metadata(self) -> Dict:
        """Extract book metadata from EPUB."""
        metadata = {}
        
        # Title
        title = self.book.get_metadata('DC', 'title')
        metadata['title'] = title[0][0] if title else "Unknown Title"
        
        # Author
        author = self.book.get_metadata('DC', 'creator')
        metadata['author'] = author[0][0] if author else "Unknown Author"
        
        # Language
        language = self.book.get_metadata('DC', 'language')
        metadata['language'] = language[0][0] if language else "en"
        
        # Publisher
        publisher = self.book.get_metadata('DC', 'publisher')
        metadata['publisher'] = publisher[0][0] if publisher else None
        
        # Date
        date = self.book.get_metadata('DC', 'date')
        if date:
            # Try to extract year
            year_match = re.search(r'\d{4}', date[0][0])
            if year_match:
                metadata['publication_year'] = int(year_match.group())
        
        # ISBN
        identifier = self.book.get_metadata('DC', 'identifier')
        if identifier:
            for ident in identifier:
                if 'isbn' in str(ident).lower():
                    metadata['isbn'] = ident[0]
                    break
        
        # Description
        description = self.book.get_metadata('DC', 'description')
        metadata['description'] = description[0][0] if description else None
        
        logger.info(f"Metadata: {metadata['title']} by {metadata['author']}")
        return metadata
    
    def _extract_text(self) -> List[str]:
        """Extract text content from all document items."""
        text_sections = []
        
        # Get all document items in reading order
        items = list(self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        
        for item in items:
            try:
                # Parse HTML content
                content = item.get_content().decode('utf-8', errors='ignore')
                soup = BeautifulSoup(content, 'html.parser')
                
                # Remove script and style elements
                for script in soup(["script", "style", "nav"]):
                    script.decompose()
                
                # Extract text from EPUB HTML, preserving headings and paragraph structure
                html_parts = []
                
                # Extract headings and paragraphs in order
                for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
                    tag_name = element.name
                    element_text = element.get_text(separator=' ', strip=True)
                    element_text = ' '.join(element_text.split())  # Clean whitespace
                    
                    if element_text:
                        if tag_name.startswith('h'):
                            # Preserve heading tags
                            html_parts.append(f'<{tag_name}>{element_text}</{tag_name}>')
                        else:
                            # Regular paragraph
                            html_parts.append(element_text)
                
                # If no structured content found, fall back to plain text
                if not html_parts:
                    text = soup.get_text()
                    text = ' '.join(text.split())
                else:
                    text = '\n\n'.join(html_parts)
                
                if text.strip():
                    text_sections.append(text.strip())
                    
            except Exception as e:
                logger.warning(f"Failed to extract text from item: {e}")
                continue
        
        return text_sections


def download_gutenberg_epub(gutenberg_id: int, output_path: str) -> str:
    """Download EPUB from Project Gutenberg."""
    import requests
    from .config import settings
    
    # Try different URL patterns for Gutenberg
    urls = [
        f"{settings.gutenberg_mirror}/ebooks/{gutenberg_id}.epub3.images",
        f"{settings.gutenberg_mirror}/ebooks/{gutenberg_id}.epub.images",
        f"{settings.gutenberg_mirror}/ebooks/{gutenberg_id}.epub.noimages",
    ]
    
    logger.info(f"Downloading Gutenberg book {gutenberg_id}...")
    
    for url in urls:
        try:
            response = requests.get(url, timeout=settings.download_timeout)
            if response.status_code == 200:
                filepath = f"{output_path}/gutenberg_{gutenberg_id}.epub"
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                logger.info(f"Downloaded {len(response.content)} bytes to {filepath}")
                return filepath
        except Exception as e:
            logger.debug(f"Failed to download from {url}: {e}")
            continue
    
    raise ValueError(f"Could not download Gutenberg book {gutenberg_id} from any URL")