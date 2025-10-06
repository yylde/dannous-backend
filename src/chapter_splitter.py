"""Intelligent chapter splitting logic with semantic boundary detection."""

import re
import logging
from typing import List, Dict, Optional
import ollama
from .config import settings

logger = logging.getLogger(__name__)


class ChapterSplitter:
    """Split text into semantically coherent reading sections."""
    
    # Scene/section break patterns (natural split points)
    SCENE_BREAK_PATTERNS = [
        r'\n\s*\*\s*\*\s*\*\s*\n',  # *** scene break
        r'\n\s*---+\s*\n',           # --- divider
        r'\n\s*•\s*•\s*•\s*\n',      # ••• break
        r'\n\s*～+\s*\n',            # ～ break
    ]
    
    # Dialogue patterns (don't split in middle of conversation)
    DIALOGUE_START = r'^["\'"]|^\s*["\'"]'
    DIALOGUE_END = r'["\'"][.,!?]?$'
    
    def __init__(self, reading_level: str = "intermediate", use_llm: bool = True):
        """Initialize chapter splitter."""
        self.reading_level = reading_level
        self.use_llm = use_llm
        self.target_words = settings.get_max_words_for_level(reading_level)
        self.min_words = settings.min_chapter_words
        
        # Allow 20% variance around target
        self.min_target = int(self.target_words * 0.8)
        self.max_target = int(self.target_words * 1.2)
        
        logger.info(f"Target range: {self.min_target}-{self.max_target} words")
    
    def _remove_table_of_contents(self, text: str) -> str:
        """Remove table of contents section if present."""
        # Common TOC patterns
        toc_patterns = [
            r'(?:TABLE OF )?CONTENTS?\.?\s*\n',
            r'CHAPTER\s+LIST\s*\n',
            r'LIST OF CHAPTERS\s*\n',
        ]
        
        # Find TOC start
        toc_start = None
        for pattern in toc_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                toc_start = match.start()
                logger.debug(f"Found TOC at position {toc_start}")
                break
        
        if toc_start is None:
            return text
        
        # Find where actual content starts after TOC
        # Look for the first real chapter that has substantial content
        lines = text[toc_start:].split('\n')
        
        toc_end = toc_start
        consecutive_short_lines = 0
        consecutive_blank_lines = 0
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Count blank lines
            if not stripped:
                consecutive_blank_lines += 1
                consecutive_short_lines = 0
                continue
            
            # Reset blank line counter
            consecutive_blank_lines = 0
            
            # TOC lines are typically short (just chapter titles)
            # If we find 3+ consecutive longer lines, we're past the TOC
            if len(stripped.split()) > 10:  # Substantial content
                consecutive_short_lines = 0
                # If we have 3 blank lines before this, TOC likely ended
                if consecutive_blank_lines >= 2:
                    toc_end = toc_start + sum(len(l) + 1 for l in lines[:i])
                    logger.info(f"Removed table of contents ({toc_end - toc_start} characters)")
                    break
            elif len(stripped.split()) <= 10:
                consecutive_short_lines += 1
            
            # If we've seen 20+ short lines, we're likely in TOC
            # Keep scanning until we find real content
            if consecutive_short_lines > 20 and len(stripped.split()) > 15:
                toc_end = toc_start + sum(len(l) + 1 for l in lines[:i])
                logger.info(f"Removed table of contents ({toc_end - toc_start} characters)")
                break
        
        # Return text without TOC
        return text[:toc_start] + text[toc_end:]
    
    def _classify_sections(self, sections: List[Dict]) -> List[Dict]:
        """Classify sections as content or metadata (no questions needed)."""
        # Front matter keywords (should appear near the beginning)
        front_matter_keywords = [
            'contents', 'table of contents', 'preface', 'foreword', 
            'introduction', 'prologue', 'dedication', 'acknowledgments',
            'acknowledgements', 'about the author', 'note to reader'
        ]
        
        # Back matter keywords (should appear near the end)
        back_matter_keywords = [
            'epilogue', 'afterword', 'appendix', 'notes', 'glossary',
            'bibliography', 'index', 'about the author', 'acknowledgments',
            'acknowledgements'
        ]
        
        total_sections = len(sections)
        
        for i, section in enumerate(sections):
            title_lower = section['title'].lower()
            is_metadata = False
            
            # Check if it's front matter (first 20% of book)
            if i < total_sections * 0.2:
                for keyword in front_matter_keywords:
                    if keyword in title_lower:
                        is_metadata = True
                        logger.info(f"Classified as front matter: {section['title']}")
                        break
            
            # Check if it's back matter (last 20% of book)
            if i > total_sections * 0.8:
                for keyword in back_matter_keywords:
                    if keyword in title_lower:
                        is_metadata = True
                        logger.info(f"Classified as back matter: {section['title']}")
                        break
            
            section['is_metadata'] = is_metadata
        
        return sections

    def split(self, text: str) -> List[Dict[str, str]]:
        """Split text into reading sections."""
        logger.info("Splitting text into reading sections...")
        
        # Split into paragraphs
        paragraphs = self._split_into_paragraphs(text)
        
        # Build sections respecting semantic boundaries
        sections = self._build_sections(paragraphs)
        
        # If using LLM, refine section titles
        if self.use_llm and len(sections) > 0:
            sections = self._refine_with_llm(sections)
        
        # Number sections
        for i, section in enumerate(sections, 1):
            section['number'] = i
        
        logger.info(f"Created {len(sections)} sections")
        return sections
    
    def _split_into_paragraphs(self, text: str) -> List[Dict]:
        """Split text into paragraphs with metadata."""
        paragraphs = []
        
        # Split by double newlines (paragraph breaks)
        raw_paragraphs = re.split(r'\n\n+', text)
        
        for para_text in raw_paragraphs:
            para_text = para_text.strip()
            if not para_text:
                continue
            
            word_count = len(para_text.split())
            
            # Detect paragraph type
            para_type = self._classify_paragraph(para_text)
            
            paragraphs.append({
                'text': para_text,
                'word_count': word_count,
                'type': para_type,
                'has_scene_break': self._has_scene_break(para_text),
                'starts_dialogue': self._starts_dialogue(para_text),
                'ends_dialogue': self._ends_dialogue(para_text)
            })
        
        return paragraphs
    
    def _classify_paragraph(self, text: str) -> str:
        """Classify paragraph type."""
        # Check for dialogue
        if re.search(r'^["\'"]', text.strip()):
            return 'dialogue'
        
        # Check for scene break
        if self._has_scene_break(text):
            return 'scene_break'
        
        # Check for chapter heading (original book structure)
        if re.match(r'^(CHAPTER|Chapter|PART|Part)\s+[IVXLCDM\d]+', text.strip()):
            return 'heading'
        
        # Default is narrative
        return 'narrative'
    
    def _has_scene_break(self, text: str) -> bool:
        """Check if text contains a scene break marker."""
        for pattern in self.SCENE_BREAK_PATTERNS:
            if re.search(pattern, text):
                return True
        return False
    
    def _starts_dialogue(self, text: str) -> bool:
        """Check if paragraph starts with dialogue."""
        return bool(re.match(self.DIALOGUE_START, text.strip()))
    
    def _ends_dialogue(self, text: str) -> bool:
        """Check if paragraph ends with dialogue."""
        return bool(re.search(self.DIALOGUE_END, text.strip()))
    
    def _build_sections(self, paragraphs: List[Dict]) -> List[Dict]:
        """Build reading sections respecting semantic boundaries."""
        sections = []
        current_section = []
        current_words = 0
        in_dialogue = False
        section_num = 1
        
        for i, para in enumerate(paragraphs):
            # Skip very short paragraphs that are likely TOC entries or headings alone
            # But keep them if they're part of a larger section
            if para['word_count'] < 5 and para['type'] == 'heading' and not current_section:
                logger.debug(f"Skipping short heading: {para['text'][:50]}")
                continue
            
            # Check if this is a good split point
            is_split_point = self._is_good_split_point(
                para, 
                current_words, 
                in_dialogue,
                i < len(paragraphs) - 1
            )
            
            # Update dialogue tracking
            if para['starts_dialogue']:
                in_dialogue = True
            if para['ends_dialogue'] and not para['starts_dialogue']:
                in_dialogue = False
            
            # If we should split here, save current section
            if is_split_point and current_section:
                section = self._finalize_section(current_section, section_num)
                # Only add sections that meet minimum word count
                if section['word_count'] >= self.min_words:
                    sections.append(section)
                    section_num += 1
                else:
                    logger.debug(f"Skipping short section ({section['word_count']} words): {section['title']}")
                current_section = []
                current_words = 0
            
            # Add paragraph to current section
            current_section.append(para)
            current_words += para['word_count']
        
        # Add final section
        if current_section:
            section = self._finalize_section(current_section, section_num)
            if section['word_count'] >= self.min_words:
                sections.append(section)
            else:
                logger.debug(f"Skipping final short section ({section['word_count']} words)")
        
        return sections
    
    def _is_good_split_point(
        self, 
        para: Dict, 
        current_words: int,
        in_dialogue: bool,
        has_next: bool
    ) -> bool:
        """Determine if this is a good place to split."""
        # Don't split if section is too short
        if current_words < self.min_target:
            return False
        
        # Don't split in middle of dialogue
        if in_dialogue and not para['ends_dialogue']:
            return False
        
        # Always split at scene breaks if we're in range
        if para['has_scene_break'] and current_words >= self.min_target:
            return True
        
        # Split at headings if we're in range
        if para['type'] == 'heading' and current_words >= self.min_target:
            return True
        
        # If we've exceeded max, find next narrative paragraph
        if current_words >= self.max_target:
            # Split at next narrative (not dialogue) if possible
            if para['type'] == 'narrative' and not in_dialogue:
                return True
            # Or at end of dialogue
            if para['ends_dialogue']:
                return True
        
        return False
    
    def _finalize_section(self, paragraphs: List[Dict], section_num: int) -> Dict:
        """Convert paragraph list into a section."""
        content = '\n\n'.join(p['text'] for p in paragraphs)
        word_count = sum(p['word_count'] for p in paragraphs)
        
        # Generate title from content
        title = self._generate_title(content, section_num)
        
        return {
            'number': section_num,
            'title': title,
            'content': content,
            'word_count': word_count,
            'paragraph_count': len(paragraphs)
        }
    
    def _generate_title(self, content: str, section_num: int) -> str:
        """Generate a descriptive title for the section."""
        # Check if content starts with a heading
        first_line = content.split('\n')[0].strip()
        if re.match(r'^(CHAPTER|Chapter|PART|Part)\s+', first_line):
            return first_line
        
        # Extract first sentence for context
        sentences = re.split(r'[.!?]+\s+', content[:500])
        if sentences and len(sentences[0]) > 20:
            # Use key words from first sentence
            first_sentence = sentences[0]
            
            # Remove common words
            words = first_sentence.split()
            important_words = [
                w for w in words 
                if len(w) > 4 and w.lower() not in {
                    'there', 'their', 'which', 'where', 'these', 'those',
                    'would', 'could', 'should', 'about', 'after', 'before'
                }
            ]
            
            if len(important_words) >= 2:
                # Create title from important words
                title_words = important_words[:3]
                return f"Section {section_num}: {' '.join(title_words)}"
        
        # Default title
        return f"Section {section_num}"
    
    def _refine_with_llm(self, sections: List[Dict]) -> List[Dict]:
        """Use LLM to generate better section titles."""
        logger.info("Refining section titles with LLM...")
        
        try:
            for section in sections:
                # Get first 200 words for context
                preview = ' '.join(section['content'].split()[:200])
                
                # Generate title with LLM
                title = self._generate_llm_title(preview, section['number'])
                if title:
                    section['title'] = title
                    
        except Exception as e:
            logger.warning(f"LLM title generation failed: {e}")
            # Continue with auto-generated titles
        
        return sections
    
    def _generate_llm_title(self, content_preview: str, section_num: int) -> Optional[str]:
        """Generate a concise, descriptive title using LLM."""
        prompt = f"""Based on this excerpt from a children's book, create a short, engaging chapter title (maximum 6 words).

The title should:
- Be appropriate for children
- Hint at what happens in this section
- Be intriguing but not a spoiler
- Be in title case

Excerpt:
{content_preview}

Respond with ONLY the title, nothing else. Do not include quotes or "Chapter X:" prefix."""

        try:
            response = ollama.generate(
                model=settings.ollama_model,
                prompt=prompt,
                options={'temperature': 0.7, 'num_predict': 20}
            )
            
            title = response['response'].strip()
            
            # Clean up the title
            title = re.sub(r'^["\'`]+|["\'`]+$', '', title)  # Remove quotes
            title = re.sub(r'^(Chapter|Section)\s+\d+:?\s*', '', title, flags=re.IGNORECASE)  # Remove prefix
            
            # Limit to 6 words
            words = title.split()
            if len(words) > 6:
                title = ' '.join(words[:6])
            
            if len(title) > 10 and len(title) < 60:  # Reasonable length
                return f"Section {section_num}: {title}"
            
        except Exception as e:
            logger.debug(f"LLM title generation failed for section {section_num}: {e}")
        
        return None


def calculate_reading_time(word_count: int, wpm: int = None) -> int:
    """Calculate estimated reading time in minutes."""
    if wpm is None:
        wpm = settings.reading_speed_wpm
    
    minutes = word_count / wpm
    return max(1, round(minutes))