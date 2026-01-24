"""Test pair for splitting large modules (god class scenario)."""

import pytest
from pathlib import Path

from refactree.refactor import RefactorStrategy
from tests.test_pairs.base import TestPair


class TestGodClassSplit(TestPair):
    """Test splitting a large module with multiple classes."""
    
    strategy = RefactorStrategy.SPLIT_LARGE_MODULES
    
    before_code = {
        Path("large_module.py"): """
class UserValidator:
    \"\"\"Validates user data.\"\"\"
    
    def validate_email(self, email: str) -> bool:
        return "@" in email
    
    def validate_password(self, pwd: str) -> bool:
        return len(pwd) >= 8


class UserService:
    \"\"\"Service for user operations.\"\"\"
    
    def create_user(self, user: dict) -> dict:
        return {"id": 1, **user}
    
    def update_user(self, user_id: int, user: dict) -> dict:
        return {"id": user_id, **user}


class PaymentValidator:
    \"\"\"Validates payment data.\"\"\"
    
    def validate_card(self, card: str) -> bool:
        return len(card) == 16
    
    def validate_amount(self, amount: float) -> bool:
        return amount > 0


class PaymentService:
    \"\"\"Service for payment operations.\"\"\"
    
    def process_payment(self, payment: dict) -> dict:
        return {"status": "processed", **payment}
    
    def refund_payment(self, payment_id: int) -> dict:
        return {"status": "refunded", "id": payment_id}
"""
    }
    
    after_code = {
        Path("user_validator.py"): """
class UserValidator:
    \"\"\"Validates user data.\"\"\"
    
    def validate_email(self, email: str) -> bool:
        return "@" in email
    
    def validate_password(self, pwd: str) -> bool:
        return len(pwd) >= 8
""",
        Path("user_service.py"): """
class UserService:
    \"\"\"Service for user operations.\"\"\"
    
    def create_user(self, user: dict) -> dict:
        return {"id": 1, **user}
    
    def update_user(self, user_id: int, user: dict) -> dict:
        return {"id": user_id, **user}
""",
        Path("payment_validator.py"): """
class PaymentValidator:
    \"\"\"Validates payment data.\"\"\"
    
    def validate_card(self, card: str) -> bool:
        return len(card) == 16
    
    def validate_amount(self, amount: float) -> bool:
        return amount > 0
""",
        Path("payment_service.py"): """
class PaymentService:
    \"\"\"Service for payment operations.\"\"\"
    
    def process_payment(self, payment: dict) -> dict:
        return {"status": "processed", **payment}
    
    def refund_payment(self, payment_id: int) -> dict:
        return {"status": "refunded", "id": payment_id}
"""
    }
    
    expected_operations = [
        "Split large_module.py into focused modules",
        "Module names follow domain_functionality pattern",
        "user_validator.py contains UserValidator",
        "user_service.py contains UserService",
        "payment_validator.py contains PaymentValidator",
        "payment_service.py contains PaymentService",
    ]

