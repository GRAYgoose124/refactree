"""Test interactive mode user-defined groups and targets."""

import pytest
from pathlib import Path

from refactree.interactive import InteractiveRefactorSession
from refactree.models import RefactorOperation, RefactorPlan, Symbol, SymbolType
from refactree.refactor import RefactorStrategy


def test_user_groups():
    """Test that user can define symbol groups."""
    # Create test symbols
    symbols = {
        "test.Symbol1": Symbol(
            name="Symbol1",
            symbol_type=SymbolType.CLASS,
            module_path=Path("module1.py"),
            line_start=1,
            line_end=10,
        ),
        "test.Symbol2": Symbol(
            name="Symbol2",
            symbol_type=SymbolType.CLASS,
            module_path=Path("module1.py"),
            line_start=11,
            line_end=20,
        ),
    }
    
    # Create test plan
    plan = RefactorPlan(
        operations=[],
        import_updates={},
        validation_required=True,
    )
    
    session = InteractiveRefactorSession(symbols, plan, RefactorStrategy.BALANCED)
    
    # Define a group
    session.user_groups["my_group"] = ["Symbol1", "Symbol2"]
    
    assert "my_group" in session.user_groups
    assert len(session.user_groups["my_group"]) == 2


def test_user_targets():
    """Test that user can specify target modules."""
    symbols = {
        "test.Symbol1": Symbol(
            name="Symbol1",
            symbol_type=SymbolType.CLASS,
            module_path=Path("module1.py"),
            line_start=1,
            line_end=10,
        ),
    }
    
    plan = RefactorPlan(
        operations=[],
        import_updates={},
        validation_required=True,
    )
    
    session = InteractiveRefactorSession(symbols, plan, RefactorStrategy.BALANCED)
    
    # Define group and target
    session.user_groups["my_group"] = ["Symbol1"]
    session.user_targets["my_group"] = Path("target_module.py")
    
    assert "my_group" in session.user_targets
    assert session.user_targets["my_group"] == Path("target_module.py")


def test_filter_operations():
    """Test that operations can be filtered."""
    symbols = {
        "test.Symbol1": Symbol(
            name="Symbol1",
            symbol_type=SymbolType.CLASS,
            module_path=Path("module1.py"),
            line_start=1,
            line_end=10,
        ),
        "test.Symbol2": Symbol(
            name="Symbol2",
            symbol_type=SymbolType.CLASS,
            module_path=Path("module1.py"),
            line_start=11,
            line_end=20,
        ),
    }
    
    operations = [
        RefactorOperation(
            symbol=symbols["test.Symbol1"],
            source_module=Path("module1.py"),
            target_module=Path("module2.py"),
            reason="Test",
        ),
        RefactorOperation(
            symbol=symbols["test.Symbol2"],
            source_module=Path("module1.py"),
            target_module=Path("module3.py"),
            reason="Test",
        ),
    ]
    
    plan = RefactorPlan(
        operations=operations,
        import_updates={},
        validation_required=True,
    )
    
    session = InteractiveRefactorSession(symbols, plan, RefactorStrategy.BALANCED)
    
    # Filter out first operation
    session.filtered_operations.add(0)
    
    # Apply changes
    modified_plan = session._apply_changes()
    
    assert len(modified_plan.operations) == 1
    assert modified_plan.operations[0].symbol.name == "Symbol2"

