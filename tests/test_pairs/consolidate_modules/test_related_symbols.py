"""Test pair for consolidating related symbols."""

from pathlib import Path

from refactree.refactor import RefactorStrategy
from tests.test_pairs.base import TestPair


class TestRelatedSymbols(TestPair):
    """Test consolidating highly coupled, semantically similar modules."""
    
    strategy = RefactorStrategy.CONSOLIDATE_MODULES
    
    before_code = {
        Path("user_validator.py"): """
def validate_email(email: str) -> bool:
    \"\"\"Validate email address.\"\"\"
    return "@" in email
""",
        Path("user_checker.py"): """
def check_email(email: str) -> bool:
    \"\"\"Check if email is valid.\"\"\"
    return "@" in email and "." in email
""",
        Path("user_verifier.py"): """
def verify_email(email: str) -> bool:
    \"\"\"Verify email format.\"\"\"
    return len(email) > 0 and "@" in email
"""
    }
    
    after_code = {
        Path("user_validator.py"): """
def validate_email(email: str) -> bool:
    \"\"\"Validate email address.\"\"\"
    return "@" in email


def check_email(email: str) -> bool:
    \"\"\"Check if email is valid.\"\"\"
    return "@" in email and "." in email


def verify_email(email: str) -> bool:
    \"\"\"Verify email format.\"\"\"
    return len(email) > 0 and "@" in email
"""
    }
    
    expected_operations = [
        "Consolidate highly coupled, semantically similar modules",
        "Only consolidates when it makes sense",
        "Doesn't consolidate into entry points",
    ]

