"""
Text tokenization for retrieval.

Supports both Chinese (via jieba) and English tokenization.
"""

import re
from typing import Optional

# Try to import jieba for Chinese tokenization
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False


def tokenize(text: str, language: Optional[str] = None) -> list[str]:
    """Tokenize text into words/tokens.
    
    Args:
        text: Text to tokenize
        language: "zh" for Chinese, "en" for English, None for auto-detect
    
    Returns:
        List of tokens (lowercase)
    """
    if not text:
        return []
    
    if language is None:
        language = detect_language(text)
    
    if language == "zh":
        return tokenize_chinese(text)
    else:
        return tokenize_english(text)


def detect_language(text: str) -> str:
    """Detect if text is primarily Chinese or English."""
    # Count Chinese characters
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(text)
    
    if total_chars == 0:
        return "en"
    
    # If more than 20% Chinese characters, treat as Chinese
    return "zh" if chinese_chars / total_chars > 0.2 else "en"


def tokenize_chinese(text: str) -> list[str]:
    """Tokenize Chinese text using jieba."""
    if not text:
        return []
    
    if JIEBA_AVAILABLE:
        # Use jieba for Chinese word segmentation
        tokens = jieba.lcut(text)
    else:
        # Fallback: character-level tokenization
        tokens = list(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text))
    
    # Filter and normalize
    result = []
    for token in tokens:
        token = token.strip().lower()
        if token and len(token) > 0:
            result.append(token)
    
    return result


def tokenize_english(text: str) -> list[str]:
    """Tokenize English text."""
    if not text:
        return []
    
    # Simple word tokenization
    tokens = re.findall(r'[a-zA-Z0-9]+', text.lower())
    
    # Filter out very short tokens
    return [t for t in tokens if len(t) > 1]


def tokenize_mixed(text: str) -> list[str]:
    """Tokenize mixed Chinese/English text."""
    if not text:
        return []
    
    # First, separate Chinese and English segments
    segments = re.split(r'([\u4e00-\u9fff]+)', text)
    
    tokens = []
    for segment in segments:
        if not segment:
            continue
        
        if re.match(r'^[\u4e00-\u9fff]+$', segment):
            # Chinese segment
            tokens.extend(tokenize_chinese(segment))
        else:
            # English segment
            tokens.extend(tokenize_english(segment))
    
    return tokens
