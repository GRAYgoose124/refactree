"""Semantic similarity calculation for symbols."""

from collections import Counter
from typing import Optional

from refactree.models import Symbol
from refactree.semantic.nlp_utils import (
    tokenize_symbol_name,
    preprocess_text,
    semantic_relatedness,
    get_synonyms,
    extract_keywords,
    NLTK_AVAILABLE,
    _lazy_download_nltk_data,
)
from refactree.semantic.conventions import ConventionDetector


def calculate_name_similarity(symbol1: Symbol, symbol2: Symbol) -> float:
    """Calculate similarity between two symbol names.
    
    Uses tokenization, synonym checking, and string similarity.
    
    Returns:
        Similarity score between 0.0 and 1.0
    """
    # Ensure NLTK data is available
    _lazy_download_nltk_data()
    
    if not symbol1.name or not symbol2.name:
        return 0.0

    # Tokenize names
    tokens1 = set(tokenize_symbol_name(symbol1.name))
    tokens2 = set(tokenize_symbol_name(symbol2.name))

    if not tokens1 or not tokens2:
        return 0.0

    # Exact token overlap (Jaccard similarity)
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    jaccard = len(intersection) / len(union) if union else 0.0

    # Semantic similarity using WordNet
    semantic_score = 0.0
    if NLTK_AVAILABLE:
        semantic_scores = []
        for token1 in tokens1:
            for token2 in tokens2:
                if token1 == token2:
                    semantic_scores.append(1.0)
                else:
                    # Check direct semantic relatedness
                    relatedness = semantic_relatedness(token1, token2)
                    semantic_scores.append(relatedness)

                    # Check if one is a synonym of the other
                    if relatedness < 0.5:
                        synonyms1 = get_synonyms(token1)
                        synonyms2 = get_synonyms(token2)
                        if token1 in synonyms2 or token2 in synonyms1:
                            semantic_scores.append(0.8)

        semantic_score = max(semantic_scores) if semantic_scores else 0.0

    # Combine Jaccard and semantic scores
    return (jaccard * 0.6) + (semantic_score * 0.4)


def calculate_docstring_similarity(symbol1: Symbol, symbol2: Symbol) -> float:
    """Calculate similarity between symbol docstrings.
    
    Returns:
        Similarity score between 0.0 and 1.0
    """
    # Ensure NLTK data is available
    _lazy_download_nltk_data()
    
    doc1 = symbol1.docstring or ""
    doc2 = symbol2.docstring or ""

    if not doc1 or not doc2:
        return 0.0

    # Extract keywords from docstrings
    keywords1 = set(extract_keywords(doc1, max_keywords=20))
    keywords2 = set(extract_keywords(doc2, max_keywords=20))

    if not keywords1 or not keywords2:
        return 0.0

    # Jaccard similarity on keywords
    intersection = keywords1 & keywords2
    union = keywords1 | keywords2
    return len(intersection) / len(union) if union else 0.0


def calculate_semantic_similarity(
    symbol1: Symbol,
    symbol2: Symbol,
    name_weight: float = 0.4,
    docstring_weight: float = 0.2,
    context_weight: float = 0.2,
    domain_weight: float = 0.2,
    convention_detector: ConventionDetector | None = None,
) -> float:
    """Calculate overall semantic similarity between two symbols.
    
    Enhanced with context-aware similarity that considers code patterns
    and domain boundaries.
    
    Args:
        symbol1: First symbol
        symbol2: Second symbol
        name_weight: Weight for name similarity (default 0.4)
        docstring_weight: Weight for docstring similarity (default 0.2)
        context_weight: Weight for context similarity (default 0.2)
        domain_weight: Weight for domain/functionality similarity (default 0.2)
        convention_detector: Optional convention detector for pattern awareness
        
    Returns:
        Overall similarity score between 0.0 and 1.0
    """
    # Name similarity
    name_sim = calculate_name_similarity(symbol1, symbol2)

    # Docstring similarity
    docstring_sim = calculate_docstring_similarity(symbol1, symbol2)

    # Context similarity (module path, nearby symbols, etc.)
    context_sim = 0.0
    if symbol1.module_path.parent == symbol2.module_path.parent:
        context_sim = 0.5  # Same directory
    if symbol1.module_path == symbol2.module_path:
        context_sim = 1.0  # Same module

    # Domain/functionality similarity (new)
    domain_sim = 0.0
    if convention_detector:
        domain1 = convention_detector.extract_domain(symbol1, [])
        domain2 = convention_detector.extract_domain(symbol2, [])
        func1 = convention_detector.extract_functionality(symbol1)
        func2 = convention_detector.extract_functionality(symbol2)

        # Domain match
        if domain1 and domain2:
            if domain1 == domain2:
                domain_sim += 0.5
            elif domain1 in domain2 or domain2 in domain1:
                domain_sim += 0.3

        # Functionality match
        if func1 and func2:
            if func1 == func2:
                domain_sim += 0.5
            elif func1 in func2 or func2 in func1:
                domain_sim += 0.3

        # Pattern match (same code pattern)
        pattern1 = convention_detector.detect_pattern(symbol1)
        pattern2 = convention_detector.detect_pattern(symbol2)
        if pattern1 == pattern2 and pattern1.value != "unknown":
            domain_sim += 0.2

        domain_sim = min(1.0, domain_sim)

    # Weighted combination
    total_weight = name_weight + docstring_weight + context_weight + domain_weight
    if total_weight == 0:
        return 0.0

    similarity = (
        (name_sim * name_weight)
        + (docstring_sim * docstring_weight)
        + (context_sim * context_weight)
        + (domain_sim * domain_weight)
    ) / total_weight

    return min(1.0, max(0.0, similarity))

