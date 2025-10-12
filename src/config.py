"""Configuration management for EPUB processing pipeline."""

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra='ignore'  # ADD THIS LINE - ignores extra fields in .env
    )
    
    # Database
    database_url: str
    
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout: int = 120
    
    # Processing defaults
    default_age_range: str = "8-12"
    default_reading_level: str = "intermediate"
    default_genre: str = "fiction"
    
    # Chapter splitting
    max_chapter_words_beginner: int = 800
    max_chapter_words_intermediate: int = 1500
    max_chapter_words_advanced: int = 2500
    min_chapter_words: int = 200
    
    # Question generation
    questions_per_chapter: int = 3
    min_answer_words: int = 20
    max_answer_words: int = 200
    
    # Reading time calculation
    reading_speed_wpm: int = 200
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    # Project Gutenberg
    gutenberg_mirror: str = "https://www.gutenberg.org"
    download_timeout: int = 60
    
    def get_max_words_for_level(self, reading_level: str) -> int:
        """Get maximum chapter words based on reading level."""
        level_map = {
            "beginner": self.max_chapter_words_beginner,
            "intermediate": self.max_chapter_words_intermediate,
            "advanced": self.max_chapter_words_advanced,
        }
        return level_map.get(reading_level.lower(), self.max_chapter_words_intermediate)


# Global settings instance
settings = Settings()