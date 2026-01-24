"""Organizational rules engine."""

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from refactree.models import Symbol
from refactree.preferences.config import RuleConfig, TagConfig


@dataclass
class OrganizationalRule:
    """A rule for organizing code."""

    name: str
    pattern: str
    target_module: Path
    priority: int = 0
    is_regex: bool = False

    def matches(self, symbol: Symbol) -> bool:
        """Check if a symbol matches this rule."""
        if self.is_regex:
            return bool(re.search(self.pattern, symbol.name))
        else:
            return fnmatch.fnmatch(symbol.name, self.pattern)


@dataclass
class SemanticTag:
    """A semantic tag for organizing symbols."""

    name: str
    keywords: list[str]
    target_module: Path

    def matches(self, symbol: Symbol, symbol_keywords: list[str]) -> bool:
        """Check if a symbol matches this tag based on keywords."""
        # Check symbol name
        name_lower = (symbol.name or "").lower()
        if any(keyword.lower() in name_lower for keyword in self.keywords):
            return True

        # Check keywords
        symbol_keywords_lower = [k.lower() for k in symbol_keywords]
        tag_keywords_lower = [k.lower() for k in self.keywords]
        return bool(set(symbol_keywords_lower) & set(tag_keywords_lower))


class RuleEngine:
    """Engine for applying organizational rules."""

    def __init__(self, rules: Optional[list[OrganizationalRule]] = None, tags: Optional[list[SemanticTag]] = None) -> None:
        self.rules = rules or []
        self.tags = tags or []

    def suggest_target(self, symbol: Symbol, symbol_keywords: Optional[list[str]] = None) -> Optional[Path]:
        """Suggest a target module for a symbol based on rules and tags.
        
        Args:
            symbol: Symbol to find target for
            symbol_keywords: Optional pre-extracted keywords for the symbol
            
        Returns:
            Suggested target module path, or None if no match
        """
        # Try rules first (higher priority)
        sorted_rules = sorted(self.rules, key=lambda r: r.priority, reverse=True)
        for rule in sorted_rules:
            if rule.matches(symbol):
                return rule.target_module

        # Try tags
        if symbol_keywords:
            for tag in self.tags:
                if tag.matches(symbol, symbol_keywords):
                    return tag.target_module

        return None

    def add_rule(self, rule: OrganizationalRule) -> None:
        """Add a rule to the engine."""
        self.rules.append(rule)

    def add_tag(self, tag: SemanticTag) -> None:
        """Add a semantic tag to the engine."""
        self.tags.append(tag)

