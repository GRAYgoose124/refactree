# Semantic Analysis & User Preferences - Implementation Summary

## What Was Implemented

### 1. Semantic Analysis Module (`refactree/semantic/`)

#### Core Components:
- **`nlp_utils.py`**: NLTK text preprocessing utilities
  - Symbol name tokenization (camelCase, snake_case)
  - Text preprocessing (tokenization, lemmatization, stopword removal)
  - Synonym detection using WordNet
  - Semantic relatedness calculation
  - Keyword extraction

- **`similarity.py`**: Semantic similarity calculation
  - Name similarity (token-based + semantic)
  - Docstring similarity (keyword-based)
  - Combined semantic similarity scoring
  - Configurable weights for different similarity types

- **`analyzer.py`**: High-level semantic analysis
  - `SemanticAnalyzer` class for analyzing symbols
  - Concept extraction from names and docstrings
  - Semantic grouping based on similarity thresholds
  - Tag generation for symbols
  - Module name suggestions based on concepts

### 2. User Preferences Module (`refactree/preferences/`)

#### Core Components:
- **`config.py`**: Configuration system
  - `UserPreferences` model using Pydantic
  - YAML configuration file support
  - Semantic analysis configuration
  - Tag and rule definitions
  - Automatic loading from `refactree.yaml` or `.refactree.yaml`

- **`rules.py`**: Organizational rules engine
  - `RuleEngine` for applying user-defined rules
  - Pattern matching (glob and regex)
  - Semantic tag matching
  - Priority-based rule application

### 3. Enhanced RefactorPlanner

#### New Strategies:
1. **`semantic-grouping`**: Groups symbols by semantic similarity
2. **`concept-based`**: Organizes by extracted concepts/topics
3. **`hybrid`**: Combines structural + semantic analysis with configurable weights
4. **`preference-weighted`**: Applies user-defined rules and tags

#### Integration:
- Planner now accepts `UserPreferences` parameter
- Semantic analyzer initialized when enabled
- Rule engine built from preferences
- All strategies respect user preferences

### 4. Updated Dependencies

Added to `pyproject.toml`:
- `scikit-learn>=1.0.0` (for similarity metrics)
- `numpy>=1.20.0` (for vector operations)
- `pyyaml>=6.0` (for YAML config support)
- `nltk>=3.9.2` (already present)

## Usage Examples

### 1. Using Semantic Strategies

```bash
# Semantic grouping
uv run main.py refactor --auto --strategy semantic-grouping .

# Concept-based organization
uv run main.py refactor --auto --strategy concept-based .

# Hybrid (structural + semantic)
uv run main.py refactor --auto --strategy hybrid .

# With user preferences
uv run main.py refactor --auto --strategy preference-weighted .
```

### 2. Configuration File (`refactree.yaml`)

```yaml
preferences:
  semantic:
    enabled: true
    weight: 0.4  # 40% semantic, 60% structural in hybrid mode
    similarity_threshold: 0.6
    use_docstrings: true
    
  rules:
    - name: "API endpoints together"
      pattern: "*Endpoint"
      target_module: "api/endpoints.py"
      priority: 10
      
    - name: "Database models"
      pattern: "*Model"
      target_module: "models/"
      priority: 5
      
  tags:
    - name: "authentication"
      keywords: ["auth", "login", "token", "session"]
      target_module: "auth/"
      
    - name: "utilities"
      keywords: ["util", "helper", "common"]
      target_module: "utils/"
```

### 3. Interactive Mode with Semantic Analysis

```bash
# See all strategies including semantic ones
uv run main.py refactor --interactive --verbose .
```

## Key Features

### Semantic Analysis
- ✅ Symbol name similarity (handles camelCase, snake_case)
- ✅ Docstring analysis and keyword extraction
- ✅ Synonym detection using WordNet
- ✅ Semantic relatedness scoring
- ✅ Concept extraction
- ✅ Automatic semantic grouping

### User Preferences
- ✅ YAML configuration support
- ✅ Custom organizational rules (glob/regex patterns)
- ✅ Semantic tags with keyword matching
- ✅ Priority-based rule application
- ✅ Configurable semantic analysis weights

### Integration
- ✅ All new strategies integrated into RefactorPlanner
- ✅ Backward compatible (semantic features are opt-in)
- ✅ CLI updated to support new strategies
- ✅ Preferences automatically loaded

## How It Addresses Your Requirements

### 1. NLP-Based Semantic Analysis ✅
- Uses NLTK for text processing
- WordNet for synonym checking
- Semantic similarity calculation
- Concept extraction from names and docstrings

### 2. More Organizational Suggestions ✅
- Semantic grouping finds related symbols beyond dependencies
- Concept-based organization groups by domain concepts
- Hybrid mode combines multiple signals
- User rules provide custom organization schemes

### 3. User Opinion & Customization ✅
- YAML configuration for user preferences
- Custom rules for pattern-based organization
- Semantic tags for keyword-based grouping
- Preference-weighted strategy respects user choices
- Users can override "optimal" suggestions with their preferences

## Next Steps (Future Enhancements)

1. **Advanced Topic Modeling**: Use LDA or similar for better concept extraction
2. **Learning from User Choices**: Track which suggestions users accept/reject
3. **Domain-Specific Vocabularies**: Support custom domain lexicons
4. **Performance Optimization**: Cache semantic analysis results
5. **Interactive Preference Collection**: CLI wizard for creating config files
6. **Multi-language Support**: Extend to other programming languages

## Testing

To test the implementation:

```bash
# Install dependencies
uv sync

# Test semantic analysis (will download NLTK data on first run)
uv run python -c "from refactree.semantic import SemanticAnalyzer; print('OK')"

# Try semantic strategies
uv run main.py refactor --interactive --dry-run .
```

## Notes

- NLTK data will be downloaded automatically on first use
- Semantic analysis is slower than structural analysis (consider caching)
- All features are backward compatible - existing code continues to work
- Semantic features are opt-in via preferences or strategy selection

