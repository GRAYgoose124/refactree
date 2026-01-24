# Refactree Upgrade Plan: NLP-Based Semantic Analysis & User-Driven Refactoring

## Overview
This upgrade adds semantic analysis capabilities using NLP to generate more intelligent organizational suggestions, while making the system more opinion-driven rather than purely "optimal" metric-based.

## Goals

### 1. Semantic Analysis Layer
- Use NLTK for text processing and semantic similarity
- Analyze symbol names, docstrings, and comments for semantic grouping
- Support synonym checking and concept-based organization
- Topic modeling to identify conceptually related symbols

### 2. User Opinion & Customization
- Allow users to define custom organizational schemes
- Support semantic tags/categories for symbols
- Let users override "optimal" suggestions with preferences
- Configurable rules via YAML/TOML
- Interactive feedback loop for refining suggestions

## Architecture Changes

### New Components

#### 1. `refactree/semantic/` Module
```
refactree/semantic/
├── __init__.py
├── analyzer.py          # Semantic analysis engine
├── similarity.py        # Symbol name/docstring similarity
├── topic_modeling.py    # Topic extraction and grouping
├── embeddings.py        # Word embeddings for semantic similarity
└── nlp_utils.py         # NLTK utilities and text preprocessing
```

#### 2. `refactree/preferences/` Module
```
refactree/preferences/
├── __init__.py
├── config.py            # User preference configuration
├── rules.py             # Custom organizational rules
└── tags.py              # Semantic tagging system
```

#### 3. Enhanced Models
- Add `SemanticTag` to `Symbol` model
- Add `UserPreference` configuration model
- Add `SemanticGroup` for concept-based grouping

## Implementation Phases

### Phase 1: Foundation (Current)
- [x] Basic refactoring infrastructure
- [x] Multiple strategy support
- [x] Interactive mode

### Phase 2: NLP Infrastructure
- [ ] Install and configure NLTK data
- [ ] Create semantic analyzer module
- [ ] Implement text preprocessing (tokenization, stemming, lemmatization)
- [ ] Basic similarity calculation (cosine similarity, Jaccard)
- [ ] Symbol name analysis (camelCase, snake_case parsing)

### Phase 3: Semantic Analysis
- [ ] Docstring analysis and extraction
- [ ] Comment analysis (extract domain concepts)
- [ ] Synonym detection using WordNet
- [ ] Semantic similarity scoring
- [ ] Topic modeling (LDA or simpler keyword-based)
- [ ] Concept-based grouping

### Phase 4: User Preferences
- [ ] YAML/TOML configuration parser
- [ ] Custom rule engine
- [ ] Semantic tag definitions
- [ ] Preference override system
- [ ] Interactive preference collection

### Phase 5: Integration
- [ ] Add semantic strategies to RefactorPlanner
- [ ] Combine semantic + structural analysis
- [ ] Weighted scoring (metrics + semantics + user preferences)
- [ ] CLI integration for semantic modes
- [ ] Preference file support

### Phase 6: Advanced Features
- [ ] Learning from user choices (preference refinement)
- [ ] Domain-specific vocabularies
- [ ] Custom embedding models
- [ ] Multi-language support (future)

## Dependencies

### Required
- `nltk>=3.9.2` (already in pyproject.toml)
- `scikit-learn>=1.0.0` (for similarity metrics, topic modeling)
- `numpy>=1.20.0` (for vector operations)

### Optional
- `gensim>=4.0.0` (for advanced topic modeling)
- `spacy>=3.0.0` (alternative NLP library, more powerful)
- `pyyaml>=6.0` (for YAML config support)

## NLTK Data Requirements

The following NLTK data will be needed:
- `punkt` - Sentence tokenization
- `stopwords` - Common stop words
- `wordnet` - Synonym and semantic relationships
- `averaged_perceptron_tagger` - Part-of-speech tagging
- `vader_lexicon` - Sentiment analysis (optional)

## New Refactoring Strategies

### Semantic Strategies
1. **semantic-grouping**: Group symbols by semantic similarity
2. **concept-based**: Organize by extracted concepts/topics
3. **domain-driven**: Use domain vocabulary for organization
4. **hybrid**: Combine structural + semantic analysis

### User-Driven Strategies
1. **custom-rules**: Apply user-defined organizational rules
2. **tag-based**: Organize by semantic tags
3. **preference-weighted**: Weight suggestions by user preferences

## Configuration Format

### Example `refactree.yaml`
```yaml
preferences:
  semantic:
    enabled: true
    weight: 0.4  # 40% semantic, 60% structural
    similarity_threshold: 0.6
    
  rules:
    - name: "API endpoints together"
      pattern: "*Endpoint"
      target_module: "api/endpoints.py"
      
    - name: "Database models"
      pattern: "*Model"
      target_module: "models/"
      
  tags:
    - name: "authentication"
      keywords: ["auth", "login", "token", "session"]
      target_module: "auth/"
      
    - name: "utilities"
      keywords: ["util", "helper", "common"]
      target_module: "utils/"
```

## API Changes

### New Methods in RefactorPlanner
```python
def plan_semantic_organize(
    self,
    similarity_threshold: float = 0.6,
    use_docstrings: bool = True,
    max_operations: int = 20
) -> RefactorPlan

def plan_concept_based(
    self,
    num_topics: int = 5,
    max_operations: int = 20
) -> RefactorPlan

def plan_with_preferences(
    self,
    preferences: UserPreferences,
    max_operations: int = 20
) -> RefactorPlan
```

### New Semantic Analyzer
```python
class SemanticAnalyzer:
    def analyze_symbols(self, symbols: dict[str, Symbol]) -> dict[str, SemanticInfo]
    def calculate_similarity(self, symbol1: Symbol, symbol2: Symbol) -> float
    def extract_concepts(self, symbols: list[Symbol]) -> list[Concept]
    def suggest_groupings(self, symbols: list[Symbol]) -> list[SemanticGroup]
```

## Testing Strategy

1. Unit tests for semantic analysis functions
2. Integration tests for NLP pipeline
3. Test with various codebases (small, medium, large)
4. Performance benchmarks (NLP can be slow)
5. User preference validation

## Performance Considerations

- NLP processing can be slow for large codebases
- Cache semantic analysis results
- Make NLP optional (opt-in feature)
- Provide fast mode (structural only)
- Parallel processing for similarity calculations

## Migration Path

1. Semantic features are opt-in (backward compatible)
2. Existing strategies continue to work
3. New strategies added alongside old ones
4. Gradual migration of users to semantic modes

## Success Metrics

- More relevant suggestions (user feedback)
- Better grouping of semantically related code
- Reduced false positives in suggestions
- User satisfaction with customization options

## Timeline Estimate

- Phase 2 (NLP Infrastructure): 2-3 days
- Phase 3 (Semantic Analysis): 3-4 days
- Phase 4 (User Preferences): 2-3 days
- Phase 5 (Integration): 2-3 days
- Phase 6 (Advanced Features): Ongoing

Total: ~2 weeks for core features

