"""NLTK utilities for text preprocessing and analysis."""

import re
from typing import List

try:
    import nltk
    from nltk.corpus import stopwords, wordnet
    from nltk.tokenize import word_tokenize
    from nltk.stem import WordNetLemmatizer
    from nltk.tag import pos_tag

    # Download required NLTK data (will be cached after first run)
    # Use a helper function to ensure all data is available
    def _ensure_nltk_data():
        """Ensure all required NLTK data is downloaded."""
        required_data = [
            ("punkt_tab", "tokenizers/punkt_tab"),
            ("punkt", "tokenizers/punkt"),  # Fallback for older NLTK
            ("stopwords", "corpora/stopwords"),
            ("wordnet", "corpora/wordnet"),
            ("averaged_perceptron_tagger", "taggers/averaged_perceptron_tagger"),
            ("omw-1.4", "corpora/omw-1.4"),  # Open Multilingual Wordnet
        ]
        
        for data_name, data_path in required_data:
            try:
                nltk.data.find(data_path)
            except LookupError:
                try:
                    nltk.download(data_name, quiet=True)
                except Exception:
                    # If punkt_tab fails, try punkt as fallback
                    if data_name == "punkt_tab":
                        try:
                            nltk.download("punkt", quiet=True)
                        except Exception:
                            pass

    # Download data on import (lazy - only when needed)
    # We'll download on first use instead of on import to avoid blocking

    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    stopwords = None
    wordnet = None
    word_tokenize = None
    WordNetLemmatizer = None
    pos_tag = None
    _ensure_nltk_data = None
except Exception as e:
    # If NLTK is installed but data download fails, mark as unavailable
    NLTK_AVAILABLE = False
    stopwords = None
    wordnet = None
    word_tokenize = None
    WordNetLemmatizer = None
    pos_tag = None
    _ensure_nltk_data = None


def _lazy_download_nltk_data() -> None:
    """Lazily download NLTK data when first needed."""
    if not NLTK_AVAILABLE:
        return
    
    if _ensure_nltk_data:
        try:
            _ensure_nltk_data()
        except Exception:
            pass
    else:
        # Manual download if function not available
        try:
            import nltk
            # Try punkt_tab first, fallback to punkt
            try:
                nltk.data.find("tokenizers/punkt_tab")
            except LookupError:
                try:
                    nltk.download("punkt_tab", quiet=True)
                except Exception:
                    try:
                        nltk.data.find("tokenizers/punkt")
                    except LookupError:
                        nltk.download("punkt", quiet=True)
        except Exception:
            pass


def split_camel_case(name: str) -> List[str]:
    """Split camelCase or PascalCase into words."""
    # Insert space before capital letters
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    # Split on underscores, spaces, and numbers
    words = re.split(r"[_\s\d]+", name)
    return [w.lower() for w in words if w]


def split_snake_case(name: str) -> List[str]:
    """Split snake_case into words."""
    return [w.lower() for w in name.split("_") if w]


def tokenize_symbol_name(name: str) -> List[str]:
    """Tokenize a symbol name (handles camelCase, snake_case, etc.)."""
    if not name:
        return []

    # Try camelCase/PascalCase first
    if re.search(r"[a-z][A-Z]", name):
        words = split_camel_case(name)
    # Try snake_case
    elif "_" in name:
        words = split_snake_case(name)
    # Single word or already separated
    else:
        words = [name.lower()]

    return [w for w in words if w and not w.isdigit()]


def _lazy_download_nltk_data() -> None:
    """Lazily download NLTK data when first needed."""
    if not NLTK_AVAILABLE or not _ensure_nltk_data:
        return
    
    try:
        # Check if punkt_tab exists, if not try to download
        try:
            nltk.data.find("tokenizers/punkt_tab")
        except LookupError:
            try:
                nltk.download("punkt_tab", quiet=True)
            except Exception:
                # Fallback to punkt
                try:
                    nltk.data.find("tokenizers/punkt")
                except LookupError:
                    nltk.download("punkt", quiet=True)
    except Exception:
        pass  # Silently fail - will use fallback methods


def preprocess_text(text: str, remove_stopwords: bool = True) -> List[str]:
    """Preprocess text for semantic analysis.
    
    Args:
        text: Input text (docstring, comment, etc.)
        remove_stopwords: Whether to remove common stop words
        
    Returns:
        List of preprocessed tokens
    """
    if not text or not NLTK_AVAILABLE:
        return []

    # Ensure NLTK data is available (lazy download)
    _lazy_download_nltk_data()

    try:
        # Convert to lowercase and tokenize
        tokens = word_tokenize(text.lower())
    except LookupError:
        # If tokenizer still not available, use simple split as fallback
        tokens = text.lower().split()

    # Remove stopwords if requested
    if remove_stopwords and stopwords:
        try:
            stop_words = set(stopwords.words("english"))
            tokens = [t for t in tokens if t not in stop_words]
        except LookupError:
            # If stopwords not available, use common English stopwords
            common_stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
            tokens = [t for t in tokens if t not in common_stopwords]

    # Remove punctuation and short tokens
    tokens = [
        t for t in tokens if t.isalnum() and len(t) > 2
    ]

    # Lemmatize (convert to root form)
    if WordNetLemmatizer and pos_tag and wordnet:
        try:
            lemmatizer = WordNetLemmatizer()
            lemmatized = []
            for word, pos in pos_tag(tokens):
                # Map POS tag to WordNet format
                pos_tag_map = {"J": wordnet.ADJ, "N": wordnet.NOUN, "V": wordnet.VERB, "R": wordnet.ADV}
                wordnet_pos = pos_tag_map.get(pos[0], wordnet.NOUN)
                lemmatized.append(lemmatizer.lemmatize(word, wordnet_pos))
            return lemmatized
        except Exception:
            # Fallback to original tokens if lemmatization fails
            return tokens
    else:
        # Fallback if NLTK components not available
        return tokens


def extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """Extract keywords from text using frequency and importance.
    
    Args:
        text: Input text
        max_keywords: Maximum number of keywords to return
        
    Returns:
        List of keywords sorted by importance
    """
    if not text:
        return []

    tokens = preprocess_text(text, remove_stopwords=True)

    # Count frequency
    from collections import Counter
    word_freq = Counter(tokens)

    # Return most common keywords
    return [word for word, _ in word_freq.most_common(max_keywords)]


def get_synonyms(word: str) -> List[str]:
    """Get synonyms for a word using WordNet.
    
    Args:
        word: Input word
        
    Returns:
        List of synonym words
    """
    if not NLTK_AVAILABLE or not wordnet:
        return []

    synonyms = set()
    for syn in wordnet.synsets(word.lower()):
        for lemma in syn.lemmas():
            synonym = lemma.name().replace("_", " ").lower()
            if synonym != word.lower():
                synonyms.add(synonym)

    return list(synonyms)


def semantic_relatedness(word1: str, word2: str) -> float:
    """Calculate semantic relatedness between two words using WordNet.
    
    Returns a score between 0.0 (unrelated) and 1.0 (very related).
    """
    if not NLTK_AVAILABLE or not wordnet:
        return 0.0

    try:
        synsets1 = wordnet.synsets(word1.lower())
        synsets2 = wordnet.synsets(word2.lower())

        if not synsets1 or not synsets2:
            return 0.0

        # Calculate maximum path similarity
        max_similarity = 0.0
        for syn1 in synsets1:
            for syn2 in synsets2:
                # Path similarity (0.0 to 1.0)
                similarity = syn1.path_similarity(syn2)
                if similarity and similarity > max_similarity:
                    max_similarity = similarity

        return max_similarity
    except Exception:
        return 0.0

