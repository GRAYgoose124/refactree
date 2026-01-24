"""Code convention detection and pattern recognition."""

from pathlib import Path
from typing import Optional

from refactree.models import Symbol, SymbolType
from pathlib import Path


class CodePattern:
    """Detected code pattern for a symbol."""

    CLI_COMMAND = "cli_command"
    TEST_FUNCTION = "test_function"
    MODEL = "model"
    VALIDATOR = "validator"
    SERVICE = "service"
    PARSER = "parser"
    HANDLER = "handler"
    MANAGER = "manager"
    UTILITY = "utility"
    ENTRY_POINT = "entry_point"
    UNKNOWN = "unknown"


class ConventionDetector:
    """Detects code patterns and conventions."""

    def __init__(self, symbols: dict[str, Symbol]) -> None:
        self.symbols = symbols
        self._pattern_cache: dict[str, CodePattern] = {}

    def detect_pattern(self, symbol: Symbol) -> CodePattern:
        """Detect the code pattern for a symbol."""
        if symbol.qualified_name in self._pattern_cache:
            return self._pattern_cache[symbol.qualified_name]

        pattern = self._analyze_symbol(symbol)
        self._pattern_cache[symbol.qualified_name] = pattern
        return pattern

    def _analyze_symbol(self, symbol: Symbol) -> CodePattern:
        """Analyze a symbol to determine its pattern."""
        name = symbol.name or ""
        name_lower = name.lower()
        module_name = symbol.module_path.stem.lower()
        module_path_str = str(symbol.module_path).lower()

        # CLI commands
        if module_name == "cli" or "cli" in module_path_str:
            if symbol.symbol_type == SymbolType.FUNCTION:
                # Check if it's decorated with @app.command (we can't detect this from AST easily,
                # but being in cli.py is a strong signal)
                return CodePattern.CLI_COMMAND

        # Test functions
        if name_lower.startswith("test_") or "test" in module_name:
            if symbol.symbol_type == SymbolType.FUNCTION:
                return CodePattern.TEST_FUNCTION

        # Entry points
        if module_name in {"main", "__main__"} or name == "__main__":
            return CodePattern.ENTRY_POINT

        # Validators
        if name_lower.endswith(("validator", "validators")):
            return CodePattern.VALIDATOR

        # Services
        if name_lower.endswith(("service", "services")):
            return CodePattern.SERVICE

        # Parsers
        if name_lower.endswith(("parser", "parsers")):
            return CodePattern.PARSER

        # Handlers
        if name_lower.endswith(("handler", "handlers")):
            return CodePattern.HANDLER

        # Managers
        if name_lower.endswith(("manager", "managers")):
            return CodePattern.MANAGER

        # Models (dataclasses, Pydantic models, etc.)
        if module_name == "models" or "model" in module_name:
            if symbol.symbol_type == SymbolType.CLASS:
                return CodePattern.MODEL

        # Utilities
        if name_lower.startswith(("util", "helper", "common", "shared")):
            return CodePattern.UTILITY
        if "util" in module_name or "helper" in module_name:
            return CodePattern.UTILITY

        return CodePattern.UNKNOWN

    def should_preserve_location(self, symbol: Symbol) -> bool:
        """Determine if a symbol should stay in its current location."""
        pattern = self.detect_pattern(symbol)

        # Never move these patterns
        preserve_patterns = {
            CodePattern.CLI_COMMAND,
            CodePattern.TEST_FUNCTION,
            CodePattern.ENTRY_POINT,
        }

        return pattern in preserve_patterns

    def learn_naming_patterns(self) -> dict[str, list[str]]:
        """Analyze existing module names to learn naming patterns.
        
        Returns:
            Dictionary mapping patterns to example module names
        """
        patterns: dict[str, list[str]] = {
            "domain_functionality": [],
            "domain_only": [],
            "functionality_only": [],
            "single_word": [],
        }

        module_names = {s.module_path.stem for s in self.symbols.values()}

        for module_name in module_names:
            parts = module_name.split("_")

            if len(parts) == 1:
                patterns["single_word"].append(module_name)
            elif len(parts) == 2:
                # Could be domain_functionality or functionality_domain
                patterns["domain_functionality"].append(module_name)
            else:
                # Multi-part names
                patterns["domain_functionality"].append(module_name)

        return patterns

    def suggest_module_name(
        self,
        symbols: list[Symbol],
        domain: Optional[str] = None,
        functionality: Optional[str] = None,
    ) -> str:
        """Suggest a module name based on learned patterns and provided domain/functionality.
        
        Avoids redundant names like validation_validator.py or config_config.py.
        """
        patterns = self.learn_naming_patterns()

        # Normalize domain and functionality to check for redundancy
        domain_lower = (domain or "").lower()
        functionality_lower = (functionality or "").lower()
        
        # Validate: prevent domain_domain.py patterns
        if domain and functionality:
            # If domain and functionality are identical, use only domain
            if domain_lower == functionality_lower:
                return domain
            # Check for semantic equivalence
            if domain_lower == functionality_lower:
                # Same word, use only domain
                return domain
            
            # Check if functionality is just domain + suffix (e.g., "validation" -> "validator")
            if functionality_lower.startswith(domain_lower) or domain_lower.startswith(functionality_lower):
                # One is a prefix of the other, use the shorter/more general one
                if len(domain_lower) <= len(functionality_lower):
                    return domain
                else:
                    return functionality
            
            # Check for common redundant patterns
            redundant_patterns = {
                ("validation", "validator"): "validation",
                ("config", "configuration"): "config",
                ("parser", "parsing"): "parser",
                ("handler", "handling"): "handler",
                ("service", "servicing"): "service",
                ("manager", "management"): "manager",
            }
            
            for (dom, func), result in redundant_patterns.items():
                if (dom in domain_lower and func in functionality_lower) or \
                   (func in domain_lower and dom in functionality_lower):
                    return result
            
            # Not redundant, use domain_functionality pattern
            candidate = f"{domain}_{functionality}"
            # Check if this pattern exists in codebase
            if candidate in {s.module_path.stem for s in self.symbols.values()}:
                return candidate
            return candidate

        # If only domain
        if domain:
            return domain

        # If only functionality
        if functionality:
            return functionality

        # Fallback: use most common pattern
        if patterns["domain_functionality"]:
            # Use the pattern from existing modules
            return patterns["domain_functionality"][0]

        # Last resort
        return "module"

    def extract_domain(self, symbol: Symbol, keywords: list[str]) -> Optional[str]:
        """Extract domain from symbol name and keywords."""
        name_lower = (symbol.name or "").lower()

        # Common domain keywords
        domain_keywords = [
            "auth",
            "authentication",
            "user",
            "payment",
            "order",
            "product",
            "cart",
            "inventory",
            "shipping",
            "notification",
            "email",
            "message",
            "file",
            "document",
            "image",
            "video",
            "database",
            "db",
            "cache",
            "session",
            "config",
            "settings",
            "preference",
            "project",
            "workspace",
            "repository",
            "git",
            "semantic",
            "validation",
            "analysis",
            "parsing",
            "refactoring",
        ]

        # Check symbol name
        for domain in domain_keywords:
            if domain in name_lower:
                return domain

        # Check keywords
        for keyword in keywords:
            keyword_lower = keyword.lower()
            for domain in domain_keywords:
                if domain in keyword_lower or keyword_lower in domain:
                    return domain

        return None

    def extract_functionality(self, symbol: Symbol) -> Optional[str]:
        """Extract functionality/role from symbol name."""
        name_lower = (symbol.name or "").lower()

        # Functionality patterns
        functionality_patterns = {
            "validator": ["validator", "validate", "validation"],
            "parser": ["parser", "parse", "parsing"],
            "handler": ["handler", "handle"],
            "service": ["service"],
            "manager": ["manager", "manage"],
            "controller": ["controller", "control"],
            "repository": ["repository", "repo"],
            "factory": ["factory"],
            "builder": ["builder", "build"],
            "executor": ["executor", "execute"],
            "planner": ["planner", "plan"],
            "analyzer": ["analyzer", "analyze", "analysis"],
            "metrics": ["metrics", "metric"],
            "graph": ["graph"],
            "similarity": ["similarity", "similar"],
            "convention": ["convention"],
            "config": ["config", "configuration"],
            "rule": ["rule", "rules"],
            "tag": ["tag", "tags"],
        }

        for functionality, patterns in functionality_patterns.items():
            for pattern in patterns:
                if pattern in name_lower:
                    return functionality

        # Check suffixes
        for functionality, patterns in functionality_patterns.items():
            for pattern in patterns:
                if name_lower.endswith(pattern) or name_lower.endswith(f"{pattern}s"):
                    return functionality

        return None

