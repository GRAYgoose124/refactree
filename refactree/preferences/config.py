"""User preference configuration system."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class SemanticConfig(BaseModel):
    """Semantic analysis configuration."""

    enabled: bool = True
    weight: float = Field(default=0.4, ge=0.0, le=1.0)  # Weight vs structural analysis
    similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    use_docstrings: bool = True
    use_comments: bool = False


class TagConfig(BaseModel):
    """Semantic tag configuration."""

    name: str
    keywords: list[str] = Field(default_factory=list)
    target_module: str


class RuleConfig(BaseModel):
    """Organizational rule configuration."""

    name: str
    pattern: str  # Glob pattern or regex
    target_module: str
    priority: int = 0  # Higher priority rules applied first


class UserPreferences(BaseModel):
    """User preferences for refactoring."""

    semantic: SemanticConfig = Field(default_factory=SemanticConfig)
    tags: list[TagConfig] = Field(default_factory=list)
    rules: list[RuleConfig] = Field(default_factory=list)
    strategy_weights: dict[str, float] = Field(default_factory=dict)


def load_preferences(config_path: Optional[Path] = None) -> UserPreferences:
    """Load user preferences from a YAML file.
    
    Args:
        config_path: Path to config file (default: refactree.yaml in project root)
        
    Returns:
        UserPreferences object
    """
    if config_path is None:
        # Look for refactree.yaml or .refactree.yaml in current directory
        for candidate in [Path("refactree.yaml"), Path(".refactree.yaml")]:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None or not config_path.exists():
        # Return default preferences
        return UserPreferences()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        # Extract preferences section
        prefs_data = config_data.get("preferences", {})

        return UserPreferences(**prefs_data)
    except Exception:
        # Return default on error
        return UserPreferences()


def save_preferences(preferences: UserPreferences, config_path: Path) -> None:
    """Save user preferences to a YAML file."""
    config_data = {"preferences": preferences.model_dump()}

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

