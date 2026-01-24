"""Semantic analyzer for code organization."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from refactree.models import Symbol, SymbolType
from refactree.semantic.similarity import calculate_semantic_similarity
from refactree.semantic.nlp_utils import extract_keywords, NLTK_AVAILABLE
from refactree.semantic.conventions import ConventionDetector


@dataclass
class SemanticInfo:
    """Semantic information about a symbol."""

    symbol: Symbol
    keywords: list[str]
    concepts: list[str]
    semantic_tags: list[str]


@dataclass
class SemanticGroup:
    """A group of semantically related symbols."""

    symbols: list[Symbol]
    concept: str
    similarity_score: float
    suggested_module: Optional[Path] = None


class SemanticAnalyzer:
    """Analyzes symbols for semantic relationships and grouping opportunities."""

    def __init__(self, symbols: dict[str, Symbol]) -> None:
        self.symbols = symbols
        self._semantic_cache: dict[str, SemanticInfo] = {}
        self.convention_detector = ConventionDetector(symbols)

    def analyze_symbol(self, symbol: Symbol) -> SemanticInfo:
        """Analyze a single symbol and extract semantic information."""
        if symbol.qualified_name in self._semantic_cache:
            return self._semantic_cache[symbol.qualified_name]

        # Extract keywords from name and docstring
        name_text = symbol.name or ""
        docstring_text = symbol.docstring or ""

        # Combine name and docstring for keyword extraction
        combined_text = f"{name_text} {docstring_text}"
        keywords = extract_keywords(combined_text, max_keywords=15)

        # Extract concepts (simplified - could use topic modeling)
        concepts = self._extract_concepts(symbol, keywords)

        # Generate semantic tags
        semantic_tags = self._generate_tags(symbol, keywords, concepts)

        info = SemanticInfo(
            symbol=symbol,
            keywords=keywords,
            concepts=concepts,
            semantic_tags=semantic_tags,
        )

        self._semantic_cache[symbol.qualified_name] = info
        return info

    def analyze_symbols(self, symbols: Optional[list[Symbol]] = None) -> dict[str, SemanticInfo]:
        """Analyze multiple symbols and return semantic information."""
        if symbols is None:
            symbols = list(self.symbols.values())

        return {sym.qualified_name: self.analyze_symbol(sym) for sym in symbols}

    def find_semantic_groups(
        self,
        symbols: Optional[list[Symbol]] = None,
        similarity_threshold: float = 0.6,
        min_group_size: int = 2,
    ) -> list[SemanticGroup]:
        """Find groups of semantically similar symbols.
        
        Args:
            symbols: Symbols to analyze (None for all)
            similarity_threshold: Minimum similarity to group (0.0-1.0)
            min_group_size: Minimum symbols per group
            
        Returns:
            List of semantic groups
        """
        if symbols is None:
            symbols = list(self.symbols.values())

        if len(symbols) < min_group_size:
            return []

        groups: list[SemanticGroup] = []
        used_symbols = set()

        # Calculate pairwise similarities
        for i, sym1 in enumerate(symbols):
            if sym1.qualified_name in used_symbols:
                continue

            group_symbols = [sym1]
            group_concepts = set()

            # Analyze first symbol
            info1 = self.analyze_symbol(sym1)
            group_concepts.update(info1.concepts)

            # Find similar symbols
            for sym2 in symbols[i + 1:]:
                if sym2.qualified_name in used_symbols:
                    continue

                similarity = calculate_semantic_similarity(sym1, sym2)

                if similarity >= similarity_threshold:
                    group_symbols.append(sym2)
                    used_symbols.add(sym2.qualified_name)

                    # Add concepts from similar symbol
                    info2 = self.analyze_symbol(sym2)
                    group_concepts.update(info2.concepts)

            # Create group if large enough
            if len(group_symbols) >= min_group_size:
                # Determine concept name from all symbols in group
                all_concepts = set(info1.concepts)
                for sym in group_symbols[1:]:
                    sym_info = self.analyze_symbol(sym)
                    all_concepts.update(sym_info.concepts)

                # Prefer domain + functionality concepts
                domain_concepts = [c for c in all_concepts if c in [
                    "auth", "user", "payment", "order", "product", "validation",
                    "parsing", "analysis", "semantic", "project", "config"
                ]]
                functionality_concepts = [c for c in all_concepts if c in [
                    "validator", "parser", "handler", "service", "manager",
                    "analyzer", "metrics", "graph", "similarity"
                ]]

                # Combine domain + functionality if available
                if domain_concepts and functionality_concepts:
                    concept = f"{domain_concepts[0]}_{functionality_concepts[0]}"
                elif domain_concepts:
                    concept = domain_concepts[0]
                elif functionality_concepts:
                    concept = functionality_concepts[0]
                elif info1.concepts:
                    concept = info1.concepts[0]
                elif info1.keywords:
                    # Filter generic keywords
                    meaningful = [k for k in info1.keywords if len(k) > 3 and k.lower() not in {
                        "get", "set", "calculate", "two", "one", "new", "old"
                    }]
                    concept = meaningful[0] if meaningful else info1.keywords[0]
                else:
                    concept = "grouped"

                # Calculate average similarity with context awareness
                if len(group_symbols) > 1:
                    similarities = [
                        calculate_semantic_similarity(
                            group_symbols[0],
                            sym,
                            convention_detector=self.convention_detector,
                        )
                        for sym in group_symbols[1:]
                    ]
                    avg_similarity = (
                        sum(similarities) / len(similarities) if similarities else 0.0
                    )
                else:
                    avg_similarity = 1.0

                # Suggest module name based on concept
                suggested_module = self._suggest_module_name(group_symbols, concept)

                groups.append(
                    SemanticGroup(
                        symbols=group_symbols,
                        concept=concept,
                        similarity_score=avg_similarity,
                        suggested_module=suggested_module,
                    )
                )

                used_symbols.add(sym1.qualified_name)

        return groups

    def suggest_groupings(
        self,
        symbols: Optional[list[Symbol]] = None,
        similarity_threshold: float = 0.6,
    ) -> list[SemanticGroup]:
        """Suggest how symbols could be grouped semantically.
        
        This is a higher-level method that may use clustering algorithms.
        """
        return self.find_semantic_groups(symbols, similarity_threshold)

    def _extract_concepts(self, symbol: Symbol, keywords: list[str]) -> list[str]:
        """Extract meaningful domain and functionality concepts."""
        concepts = []

        # Extract domain using convention detector
        domain = self.convention_detector.extract_domain(symbol, keywords)
        if domain:
            concepts.append(domain)

        # Extract functionality/role
        functionality = self.convention_detector.extract_functionality(symbol)
        if functionality:
            concepts.append(functionality)

        # Filter out generic keywords that don't add value
        generic_words = {
            "get",
            "set",
            "calculate",
            "two",
            "one",
            "new",
            "old",
            "first",
            "second",
            "make",
            "create",
            "build",
            "do",
            "run",
            "use",
            "call",
            "add",
            "remove",
            "find",
            "check",
        }

        # Add meaningful keywords (not generic)
        meaningful_keywords = [
            k for k in keywords if k.lower() not in generic_words and len(k) > 3
        ]

        # Take top 2 meaningful keywords
        concepts.extend(meaningful_keywords[:2])

        # Remove duplicates while preserving order
        seen = set()
        unique_concepts = []
        for concept in concepts:
            concept_lower = concept.lower()
            if concept_lower not in seen:
                seen.add(concept_lower)
                unique_concepts.append(concept)

        return unique_concepts

    def _generate_tags(self, symbol: Symbol, keywords: list[str], concepts: list[str]) -> list[str]:
        """Generate semantic tags for a symbol."""
        tags = []

        # Add concept tags
        tags.extend(concepts)

        # Add type-based tags
        if symbol.symbol_type.value == "class":
            tags.append("class")
        elif symbol.symbol_type.value == "function":
            tags.append("function")

        # Add domain tags based on keywords
        keyword_str = " ".join(keywords).lower()
        if any(word in keyword_str for word in ["http", "request", "response", "api"]):
            tags.append("http")
        if any(word in keyword_str for word in ["data", "store", "save", "load"]):
            tags.append("data")
        if any(word in keyword_str for word in ["validate", "check", "verify"]):
            tags.append("validation")

        return list(set(tags))  # Remove duplicates

    def _suggest_module_name(self, symbols: list[Symbol], concept: str) -> Optional[Path]:
        """Suggest a module path based on domain, functionality, and existing patterns."""
        if not symbols:
            return None

        # Use the most common parent directory
        parent_dirs = defaultdict(int)
        for sym in symbols:
            parent_dirs[sym.module_path.parent] += 1

        if not parent_dirs:
            return None

        # Get most common parent
        common_parent = max(parent_dirs.items(), key=lambda x: x[1])[0]

        # Extract domain and functionality from concepts
        domain = None
        functionality = None

        # Analyze symbols to extract domain and functionality
        for symbol in symbols[:5]:  # Sample to avoid O(n²)
            sym_domain = self.convention_detector.extract_domain(symbol, [])
            sym_functionality = self.convention_detector.extract_functionality(symbol)

            if sym_domain and not domain:
                domain = sym_domain
            if sym_functionality and not functionality:
                functionality = sym_functionality

        # Also try to extract from concept string directly
        concept_lower = concept.lower()
        if not domain:
            # Check if concept itself is a domain keyword
            domain_keywords = [
                "auth", "user", "payment", "order", "product", "validation",
                "parsing", "analysis", "semantic", "project", "config"
            ]
            for dkw in domain_keywords:
                if dkw in concept_lower:
                    domain = dkw
                    break
        
        if not functionality:
            # Check if concept itself is a functionality keyword
            functionality_keywords = [
                "validator", "parser", "handler", "service", "manager",
                "analyzer", "metrics", "graph", "similarity"
            ]
            for fkw in functionality_keywords:
                if fkw in concept_lower:
                    functionality = fkw
                    break
        
        # Check for redundancy: if domain and functionality are the same concept
        # e.g., "validation" domain + "validator" functionality -> use only "validation"
        if domain and functionality:
            domain_lower = domain.lower()
            func_lower = functionality.lower()
            
            # If they're the same or one is a variant of the other, use domain only
            if domain_lower == func_lower or \
               domain_lower.startswith(func_lower) or \
               func_lower.startswith(domain_lower):
                functionality = None  # Don't create redundant name
            # Check for known redundant patterns
            elif (domain_lower == "validation" and func_lower == "validator") or \
                 (domain_lower == "validator" and func_lower == "validation"):
                functionality = None
            elif (domain_lower == "config" and func_lower == "configuration") or \
                 (domain_lower == "configuration" and func_lower == "config"):
                functionality = None

        # Generate module name using convention detector
        module_stem = self.convention_detector.suggest_module_name(
            symbols, domain=domain, functionality=functionality
        )

        # Fallback to concept if no better name found
        if not module_stem or module_stem == "module":
            module_stem = concept.lower().replace(" ", "_")

        # Clean up the name
        module_stem = module_stem.replace(" ", "_").replace("-", "_")
        if not module_stem.endswith(".py"):
            module_stem += ".py"

        return common_parent / module_stem

