"""Test pair for semantic grouping (domain separation)."""

from pathlib import Path

from refactree.refactor import RefactorStrategy
from tests.test_pairs.base import TestPair


class TestDomainSeparation(TestPair):
    """Test grouping symbols by domain."""
    
    strategy = RefactorStrategy.SEMANTIC_GROUPING
    
    before_code = {
        Path("mixed.py"): """
def validate_user_email(email: str) -> bool:
    \"\"\"Validate user email address.\"\"\"
    return "@" in email


def create_user_account(user: dict) -> dict:
    \"\"\"Create a new user account.\"\"\"
    return {"id": 1, **user}


def process_payment_card(card: str) -> dict:
    \"\"\"Process payment with card.\"\"\"
    return {"status": "processed", "card": card}


def refund_payment(payment: dict) -> dict:
    \"\"\"Refund a payment.\"\"\"
    return {"status": "refunded", **payment}
"""
    }
    
    after_code = {
        Path("user_validator.py"): """
def validate_user_email(email: str) -> bool:
    \"\"\"Validate user email address.\"\"\"
    return "@" in email
""",
        Path("user_service.py"): """
def create_user_account(user: dict) -> dict:
    \"\"\"Create a new user account.\"\"\"
    return {"id": 1, **user}
""",
        Path("payment_service.py"): """
def process_payment_card(card: str) -> dict:
    \"\"\"Process payment with card.\"\"\"
    return {"status": "processed", "card": card}


def refund_payment(payment: dict) -> dict:
    \"\"\"Refund a payment.\"\"\"
    return {"status": "refunded", **payment}
"""
    }
    
    expected_operations = [
        "Group symbols by domain (user vs payment)",
        "Related functionality kept together",
        "Module names are meaningful",
    ]

