"""Test pair for concept-based domain extraction."""

from pathlib import Path

from refactree.refactor import RefactorStrategy
from tests.test_pairs.base import TestPair


class TestDomainExtraction(TestPair):
    """Test extracting symbols by domain concept."""
    
    strategy = RefactorStrategy.CONCEPT_BASED
    
    before_code = {
        Path("utils.py"): """
def validate_user_data(data: dict) -> bool:
    \"\"\"Validate user data.\"\"\"
    return "email" in data and "name" in data


def process_payment_info(info: dict) -> dict:
    \"\"\"Process payment information.\"\"\"
    return {"processed": True, **info}


def check_inventory_levels(levels: dict) -> dict:
    \"\"\"Check inventory levels.\"\"\"
    return {"checked": True, **levels}
"""
    }
    
    after_code = {
        Path("user_validator.py"): """
def validate_user_data(data: dict) -> bool:
    \"\"\"Validate user data.\"\"\"
    return "email" in data and "name" in data
""",
        Path("payment_service.py"): """
def process_payment_info(info: dict) -> dict:
    \"\"\"Process payment information.\"\"\"
    return {"processed": True, **info}
""",
        Path("inventory_service.py"): """
def check_inventory_levels(levels: dict) -> dict:
    \"\"\"Check inventory levels.\"\"\"
    return {"checked": True, **levels}
"""
    }
    
    expected_operations = [
        "Extract symbols by domain concept",
        "Module names reflect domain",
        "Generic 'utils' broken down",
    ]

