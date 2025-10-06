"""Intelligent chapter splitting logic."""

import re
import logging
from typing import List, Dict
from .config import settings

logger = logging.getLogger(__name__)


class ChapterSplitter:
    """Split text into chapters and sub-chapters."""
    
    # Chapter detection patterns
    CHAPTER_PATTERNS = [
        r'^CHAPTER\s+([IVXLCDM]+|\d+|[A-Z][a-z]+)',  # CHAPTER I, CHAPTER 1, CHAPTER One
        r'^Chapter\s+(\d+|[A-Z][a-z]+)',              # Chapter 1, Chapter One
        r'^PART\s+([IVXLCDM]+|\d+)',                  # PART I, PART 1
        r'^Part\s+(\d+)',                             # Part 1
        r'^[IVXLCDM]+\.\s*$',                         # Roman numerals alone
        r'^\d+\.\s*$',                                # Numbers alone
    ]
    
    def __init__(self, reading_level: str = "intermediate"):
        """Initialize chapter splitter."""
        self.reading_level = reading_level
        self.max_words = settings.get_max_words_for_level(reading_level)
        self.min_words = settings.min_chapter_words
    
    def split(self, text: str) -> List[Dict[str, str]]:
        """Split text into chapters."""
        logger.info("Splitting text into chapters...")
        
        # Try to detect natural chapters
        chapters = self._detect_chapters(text)
        
        if not chapters:
            logger.warning("No chapters detected, creating sections by length")
            chapters = self._split_by_length(text)
        else:
            logger.info(f"Detected {len(chapters)} natural chapters")
            # Check if any chapters need splitting
            chapters = self._split_long_chapters(chapters)
        
        # Number chapters sequentially
        for i, chapter in enumerate(chapters, 1):
            if 'number' not in chapter:
                chapter['number'] = i
        
        logger.info(f"Final: {len(chapters)} chapters")
        return chapters
    
    def _detect_chapters(self, text: str) -> List[Dict[str, str]]:
        """Detect chapter boundaries using patterns."""
        chapters = []
        lines = text.split('\n')
        
        chapter_starts = []
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # Check each pattern
            for pattern in self.CHAPTER_PATTERNS:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    chapter_starts.append({
                        'line_num': i,
                        'title': line_stripped
                    })
                    break
        
        # If we found chapter markers, split the text
        if len(chapter_starts) >= 2:
            for i, start in enumerate(chapter_starts):
                # Get content until next chapter or end
                start_line = start['line_num']
                end_line = chapter_starts[i + 1]['line_num'] if i + 1 < len(chapter_starts) else len(lines)
                
                content_lines = lines[start_line + 1:end_line]
                content = '\n'.join(content_lines).strip()
                
                if content:
                    chapters.append({
                        'number': i + 1,
                        'title': start['title'],
                        'content': content,
                        'word_count': len(content.split())
                    })
        
        return chapters
    
    def _split_by_length(self, text: str) -> List[Dict[str, str]]:
        """Split text into sections by target length."""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        chapters = []
        current_chapter = []
        current_words = 0
        chapter_num = 1
        
        for para in paragraphs:
            para_words = len(para.split())
            
            # If adding this paragraph exceeds limit, start new chapter
            if current_words + para_words > self.max_words and current_chapter:
                chapters.append({
                    'number': chapter_num,
                    'title': f"Section {chapter_num}",
                    'content': '\n\n'.join(current_chapter),
                    'word_count': current_words
                })
                current_chapter = []
                current_words = 0
                chapter_num += 1
            
            current_chapter.append(para)
            current_words += para_words
        
        # Add final chapter
        if current_chapter:
            chapters.append({
                'number': chapter_num,
                'title': f"Section {chapter_num}",
                'content': '\n\n'.join(current_chapter),
                'word_count': current_words
            })
        
        return chapters
    
    def _split_long_chapters(self, chapters: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Split chapters that are too long."""
        result = []
        
        for chapter in chapters:
            if chapter['word_count'] <= self.max_words:
                result.append(chapter)
            else:
                # Split this chapter
                logger.info(
                    f"Splitting chapter {chapter['number']} "
                    f"({chapter['word_count']} words) into parts"
                )
                parts = self._split_chapter_into_parts(chapter)
                result.extend(parts)
        
        return result
    
    def _split_chapter_into_parts(self, chapter: Dict[str, str]) -> List[Dict[str, str]]:
        """Split a single chapter into multiple parts."""
        paragraphs = [p.strip() for p in chapter['content'].split('\n\n') if p.strip()]
        
        parts = []
        current_part = []
        current_words = 0
        part_num = 1
        
        for para in paragraphs:
            para_words = len(para.split())
            
            if current_words + para_words > self.max_words and current_part:
                parts.append({
                    'number': chapter['number'],
                    'title': f"{chapter['title']} - Part {part_num}",
                    'content': '\n\n'.join(current_part),
                    'word_count': current_words
                })
                current_part = []
                current_words = 0
                part_num += 1
            
            current_part.append(para)
            current_words += para_words
        
        # Add final part
        if current_part:
            parts.append({
                'number': chapter['number'],
                'title': f"{chapter['title']} - Part {part_num}",
                'content': '\n\n'.join(current_part),
                'word_count': current_words
            })
        
        return parts


def calculate_reading_time(word_count: int, wpm: int = None) -> int:
    """Calculate estimated reading time in minutes."""
    if wpm is None:
        wpm = settings.reading_speed_wpm
    
    minutes = word_count / wpm
    return max(1, round(minutes))