"""Regression test for redundant module names."""

from pathlib import Path

from refactree.refactor import RefactorStrategy
from tests.test_pairs.base import TestPair


class TestNoRedundantNames(TestPair):
    """Test that redundant names like validation_validator.py are not created."""
    
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
"""
    }
    
    expected_operations = [
        "Module name is validation.py, NOT validation_validator.py",
        "All validation-related symbols grouped together",
        "No redundant domain_functionality when they're the same",
    ]

