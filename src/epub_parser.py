"""EPUB file parsing and text extraction."""

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
import logging
import re
import base64

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
            
            # Extract text content - now returns both HTML and plain text
            html_sections, text_sections = self._extract_text()
            
            # Store for backward compatibility
            self.chapters_raw = text_sections
            
            logger.info(
                f"Extracted {len(text_sections)} sections, "
                f"~{sum(len(c.split()) for c in text_sections)} words"
            )
            
            return {
                "metadata": self.metadata,
                "raw_text": "\n\n".join(text_sections),
                "raw_html": "\n\n".join(html_sections),
                "sections": text_sections,
                "html_sections": html_sections
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
    
    def _extract_images(self) -> Dict[str, str]:
        """Extract images from EPUB and convert to base64 data URIs.
        
        Returns:
            Dict mapping image filenames/IDs to base64 data URIs
        """
        image_map = {}
        
        if not self.book:
            return image_map
        
        # Get all image items (convert generator to list)
        images = list(self.book.get_items_of_type(ebooklib.ITEM_IMAGE))
        
        for img in images:
            try:
                # Get image filename/ID
                img_id = img.get_name()
                
                # Get image content
                img_content = img.get_content()
                
                # Get image media type
                media_type = img.media_type
                
                # Convert to base64
                img_base64 = base64.b64encode(img_content).decode('utf-8')
                
                # Create data URI
                data_uri = f"data:{media_type};base64,{img_base64}"
                
                # Map both the full path and just the filename
                image_map[img_id] = data_uri
                # Also map just the filename for cases where src is relative
                filename = img_id.split('/')[-1]
                if filename != img_id:
                    image_map[filename] = data_uri
                
                logger.debug(f"Extracted image: {img_id}")
                
            except Exception as e:
                logger.warning(f"Failed to extract image: {e}")
                continue
        
        logger.info(f"Extracted {len(images)} images")
        return image_map
    
    def _extract_text(self) -> Tuple[List[str], List[str]]:
        """Extract text content from all document items.
        
        Returns:
            Tuple of (html_sections, text_sections)
            - html_sections: HTML with structure preserved (includes images as base64)
            - text_sections: Plain text only
        """
        # Extract images first
        image_map = self._extract_images()
        
        html_sections = []
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
                
                # Replace img src attributes with base64 data URIs
                for img in soup.find_all('img'):
                    src = img.get('src')
                    if src:
                        # Try to find the image in the map
                        # Try exact match first
                        if src in image_map:
                            img['src'] = image_map[src]
                        else:
                            # Try just the filename
                            filename = src.split('/')[-1]
                            if filename in image_map:
                                img['src'] = image_map[filename]
                
                # Extract HTML content, preserving structure and formatting
                html_parts = []
                text_parts = []
                
                # Extract headings, paragraphs, tables, and standalone images in order
                for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'img', 'table']):
                    tag_name = element.name
                    
                    if tag_name.startswith('h'):
                        # Preserve heading tags with text
                        element_text = element.get_text(separator=' ', strip=True)
                        element_text = ' '.join(element_text.split())
                        if element_text:
                            html_parts.append(f'<{tag_name}>{element_text}</{tag_name}>')
                            text_parts.append(element_text)
                    elif tag_name == 'img':
                        # Only add standalone images (not inside paragraphs)
                        if element.parent and element.parent.name != 'p':
                            html_parts.append(str(element))
                            # For text version, add alt text if available
                            alt_text = element.get('alt', '')
                            if alt_text:
                                text_parts.append(f"[Image: {alt_text}]")
                    elif tag_name == 'table':
                        # Preserve table HTML structure completely
                        html_parts.append(str(element))
                        # For plain text, extract table content row by row
                        table_text = element.get_text(separator=' ', strip=True)
                        table_text = ' '.join(table_text.split())
                        if table_text:
                            text_parts.append(table_text)
                    else:
                        # For paragraphs, preserve inner HTML with formatting tags and images
                        # Also preserve paragraph-level attributes (style, class, id)
                        inner_html = self._extract_formatted_html(element)
                        if inner_html.strip():
                            # Build attributes string from paragraph element
                            attrs = self._extract_attributes(element)
                            if attrs:
                                html_parts.append(f'<p {attrs}>{inner_html}</p>')
                            else:
                                html_parts.append(f'<p>{inner_html}</p>')
                            # Also extract plain text version
                            plain_text = element.get_text(separator=' ', strip=True)
                            plain_text = ' '.join(plain_text.split())
                            if plain_text:
                                text_parts.append(plain_text)
                
                # If no structured content found, fall back to plain text wrapped in paragraph
                if not html_parts:
                    text = soup.get_text()
                    text = ' '.join(text.split())
                    if text:
                        html_parts.append(f'<p>{text}</p>')
                        text_parts.append(text)
                
                if html_parts:
                    html_content = '\n\n'.join(html_parts)
                    text_content = '\n\n'.join(text_parts)
                    if html_content.strip():
                        html_sections.append(html_content.strip())
                        text_sections.append(text_content.strip())
                    
            except Exception as e:
                logger.warning(f"Failed to extract text from item: {e}")
                continue
        
        return html_sections, text_sections
    
    def _extract_attributes(self, element) -> str:
        """Extract relevant attributes from an element and return as a string.
        
        Preserves: style, class, id
        Excludes: navigation/tracking attributes
        """
        attrs = []
        
        # Preserve style attribute
        if element.get('style'):
            attrs.append(f'style="{element.get("style")}"')
        
        # Preserve class attribute
        if element.get('class'):
            class_val = ' '.join(element.get('class')) if isinstance(element.get('class'), list) else element.get('class')
            attrs.append(f'class="{class_val}"')
        
        # Preserve id attribute
        if element.get('id'):
            attrs.append(f'id="{element.get("id")}"')
        
        return ' '.join(attrs)
    
    def _extract_formatted_html(self, element) -> str:
        """Extract HTML from element, preserving all formatting including br tags, entities, and styles."""
        from bs4.element import NavigableString
        
        result = []
        for content in element.children:
            if isinstance(content, NavigableString):
                # Preserve the original string exactly, including &nbsp; and all whitespace
                text = str(content)
                if text:
                    result.append(text)
            else:
                # HTML element - preserve most tags with their attributes
                if content.name == 'br':
                    # Preserve <br> tags exactly
                    result.append('<br>')
                elif content.name == 'img':
                    # Preserve img tag (src already replaced with base64)
                    result.append(str(content))
                elif content.name in ['em', 'i', 'strong', 'b', 'u', 'sup', 'sub', 'span', 'div']:
                    # Preserve formatting tags with ALL their attributes (style, class, etc.)
                    result.append(str(content))
                elif content.name == 'a':
                    # For links, just extract the text (don't need href in chapter content)
                    inner_text = content.get_text()
                    if inner_text:
                        result.append(inner_text)
                else:
                    # For other nested tags, recurse to preserve their inner formatting
                    inner_html = self._extract_formatted_html(content)
                    if inner_html:
                        result.append(inner_html)
        
        return ''.join(result)


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