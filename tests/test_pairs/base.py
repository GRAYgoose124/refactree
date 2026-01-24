"""Base class for test pairs."""

from pathlib import Path
from typing import Optional

from refactree.models import RefactorPlan, Symbol
from refactree.refactor import RefactorStrategy

from tests.helpers import (
    compare_code_structure,
    parse_code_to_symbols,
    apply_refactoring_plan,
)


class TestPair:
    """Base class for refactoring test pairs.
    
    Each test pair defines:
    - before_code: Code structure before refactoring
    - after_code: Expected code structure after refactoring
    - strategy: Which refactoring strategy should produce this result
    - expected_operations: Description of expected changes
    """
    
    strategy: RefactorStrategy
    before_code: dict[Path, str]
    after_code: dict[Path, str]
    expected_operations: list[str]
    
    def validate(self, plan: RefactorPlan) -> tuple[bool, list[str]]:
        """Validate that plan produces expected result.
        
        Args:
            plan: RefactorPlan to validate
            
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        # Apply plan to before_code
        result = apply_refactoring_plan(self.before_code, plan)
        
        # Compare result to after_code
        is_valid, issues = compare_code_structure(
            self.before_code,
            result,
            self.expected_operations,
        )
        
        # Additional validation: check expected operations are present
        operation_descriptions = [op.reason for op in plan.operations]
        for expected_op in self.expected_operations:
            if not any(expected_op.lower() in desc.lower() for desc in operation_descriptions):
                issues.append(f"Expected operation not found: {expected_op}")
        
        return is_valid, issues
    
    def get_symbols(self) -> dict[str, Symbol]:
        """Get all symbols from before_code.
        
        Returns:
            Dictionary of symbols keyed by qualified_name
        """
        all_symbols = {}
        for module_path, code in self.before_code.items():
            symbols = parse_code_to_symbols(code, module_path)
            all_symbols.update(symbols)
        return all_symbols

