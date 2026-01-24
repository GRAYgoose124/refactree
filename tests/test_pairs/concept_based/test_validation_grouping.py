"""Test for proper validation grouping."""

from pathlib import Path

from refactree.refactor import RefactorStrategy
from tests.test_pairs.base import TestPair


class TestValidationGrouping(TestPair):
    """Test that validation symbols group together properly."""
    
    strategy = RefactorStrategy.CONCEPT_BASED
    
    before_code = {
        Path("validator.py"): """
class ValidationIssue:
    \"\"\"Represents a validation issue.\"\"\"
    pass


class ValidationResult:
    \"\"\"Represents a validation result.\"\"\"
    pass


class CombinedValidator:
    \"\"\"Combines multiple validators.\"\"\"
    pass
""",
        Path("config.py"): """
class SemanticConfig:
    \"\"\"Configuration for semantic analysis.\"\"\"
    pass


class TagConfig:
    \"\"\"Configuration for tags.\"\"\"
    pass


class RuleConfig:
    \"\"\"Configuration for rules.\"\"\"
    pass
"""
    }
    
    after_code = {
        Path("validation.py"): """
class ValidationIssue:
    \"\"\"Represents a validation issue.\"\"\"
    pass


class ValidationResult:
    \"\"\"Represents a validation result.\"\"\"
    pass


class CombinedValidator:
    \"\"\"Combines multiple validators.\"\"\"
    pass
""",
        Path("config.py"): """
class SemanticConfig:
    \"\"\"Configuration for semantic analysis.\"\"\"
    pass


class TagConfig:
    \"\"\"Configuration for tags.\"\"\"
    pass


class RuleConfig:
    \"\"\"Configuration for rules.\"\"\"
    pass
"""
    }
    
    expected_operations = [
        "Validation symbols grouped together in validation.py",
        "Config symbols stay in config.py (NOT config_config.py)",
        "No redundant naming",
    ]

