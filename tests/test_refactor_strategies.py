"""Main test file for refactoring strategies."""

import pytest
from pathlib import Path

from refactree.analyzer.graph import DependencyGraph
from refactree.analyzer.metrics import CouplingMetrics
from refactree.refactor import RefactorPlanner, RefactorStrategy
from refactree.semantic import SemanticAnalyzer

from tests.test_pairs.base import TestPair
from tests.test_pairs.split_large_modules.test_god_class import TestGodClassSplit
from tests.test_pairs.semantic_grouping.test_domain_separation import TestDomainSeparation
from tests.test_pairs.consolidate_modules.test_related_symbols import TestRelatedSymbols
from tests.test_pairs.concept_based.test_domain_extraction import TestDomainExtraction
from tests.test_pairs.concept_based.test_no_redundant_names import TestNoRedundantNames
from tests.test_pairs.concept_based.test_validation_grouping import TestValidationGrouping


# Collect all test pairs
TEST_PAIRS = [
    TestGodClassSplit(),
    TestDomainSeparation(),
    TestRelatedSymbols(),
    TestDomainExtraction(),
    TestNoRedundantNames(),
    TestValidationGrouping(),
]


@pytest.mark.parametrize("test_pair", TEST_PAIRS)
def test_refactor_strategy(test_pair: TestPair):
    """Test that a refactoring strategy produces expected results."""
    # Get symbols from test pair
    symbols = test_pair.get_symbols()
    
    # Build dependency graph and metrics
    graph = DependencyGraph()
    # Create minimal dependencies for testing
    from refactree.models import Dependency, EdgeType
    dependencies = []
    graph.build(symbols, dependencies)
    
    metrics = CouplingMetrics(graph, symbols)
    
    # Create planner
    from refactree.preferences import UserPreferences
    preferences = UserPreferences()
    
    # Enable semantic analysis for strategies that need it
    if test_pair.strategy in [
        RefactorStrategy.SEMANTIC_GROUPING,
        RefactorStrategy.CONCEPT_BASED,
        RefactorStrategy.HYBRID,
        RefactorStrategy.PREFERENCE_WEIGHTED,
    ]:
        try:
            preferences.semantic.enabled = True
        except Exception:
            # NLTK might not be available, skip semantic tests
            pytest.skip("NLTK not available for semantic analysis")
    
    planner = RefactorPlanner(graph, symbols, metrics, preferences)
    
    # Generate plan
    plan = planner.plan_auto_organize(
        strategy=test_pair.strategy,
        max_operations=50,
    )
    
    # Validate plan
    is_valid, issues = test_pair.validate(plan)
    
    if not is_valid:
        error_msg = f"Strategy {test_pair.strategy.value} failed validation:\n"
        error_msg += "\n".join(f"  - {issue}" for issue in issues)
        pytest.fail(error_msg)


def test_no_redundant_module_names():
    """Test that no redundant module names are created."""
    from tests.helpers import validate_module_name
    
    # Test cases that should be invalid (redundant)
    invalid_names = [
        "validation_validator",
        "config_config",
        "parser_parser",
        "handler_handler",
    ]
    
    for name in invalid_names:
        assert not validate_module_name(name), f"{name} should be invalid (redundant)"
    
    # Test cases that should be valid
    valid_names = [
        "validation",
        "config",
        "user_validator",
        "payment_service",
        "auth_handler",
    ]
    
    for name in valid_names:
        assert validate_module_name(name), f"{name} should be valid"

