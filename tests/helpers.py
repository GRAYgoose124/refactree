"""Test helper utilities for refactoring strategy tests."""

from pathlib import Path
from typing import Optional

from refactree.analyzer.ast_parser import ASTParser
from refactree.models import RefactorPlan, Symbol
from refactree.refactor.executor import RefactorExecutor


def parse_code_to_symbols(code: str, module_path: Path) -> dict[str, Symbol]:
    """Parse Python code string and return symbols dict.
    
    Args:
        code: Python code as string
        module_path: Path for the module (used for symbol module_path)
        
    Returns:
        Dictionary of symbols keyed by qualified_name
    """
    # Create a temporary file to parse
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = Path(tmpdir) / module_path.name
        tmp_file.write_text(code, encoding="utf-8")
        
        # Parse using ASTParser
        parser = ASTParser(Path(tmpdir))
        symbols_list, _ = parser.parse_file(tmp_file)
        
        # Convert to dict keyed by qualified_name
        symbols_dict = {}
        for symbol in symbols_list:
            # Update module_path to match expected
            symbol.module_path = module_path
            symbols_dict[symbol.qualified_name] = symbol
        
        return symbols_dict


def apply_refactoring_plan(
    code_structure: dict[Path, str],
    plan: RefactorPlan,
    project_root: Optional[Path] = None,
) -> dict[Path, str]:
    """Apply refactoring plan to code structure.
    
    Args:
        code_structure: Dictionary mapping module paths to code strings
        plan: RefactorPlan to apply
        project_root: Optional project root path
        
    Returns:
        New code structure after refactoring
    """
    import tempfile
    import shutil
    
    if project_root is None:
        project_root = Path.cwd()
    
    # Create temporary project structure
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir) / "project"
        tmp_root.mkdir()
        
        # Write all code files
        for module_path, code in code_structure.items():
            full_path = tmp_root / module_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(code, encoding="utf-8")
        
        # Apply refactoring using RefactorExecutor
        executor = RefactorExecutor(tmp_root)
        executor.execute(plan)
        
        # Read back the modified structure
        result = {}
        for module_path in code_structure.keys():
            full_path = tmp_root / module_path
            if full_path.exists():
                result[module_path] = full_path.read_text(encoding="utf-8")
            else:
                # Module was moved/renamed, find it
                for new_path in tmp_root.rglob(module_path.name):
                    if new_path.is_file():
                        result[new_path.relative_to(tmp_root)] = new_path.read_text(encoding="utf-8")
                        break
        
        # Also check for new modules created by the plan
        for op in plan.operations:
            target = tmp_root / op.target_module
            if target.exists() and target not in [tmp_root / p for p in result.keys()]:
                result[op.target_module] = target.read_text(encoding="utf-8")
        
        return result


def extract_module_structure(code: str) -> dict[str, list[str]]:
    """Extract which symbols are in which modules from code.
    
    Args:
        code: Python code string (can be multi-module)
        
    Returns:
        Dictionary mapping module names to list of symbol names
    """
    import ast
    
    structure = {}
    
    try:
        tree = ast.parse(code)
        current_module = "module"
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if current_module not in structure:
                    structure[current_module] = []
                structure[current_module].append(node.name)
            elif isinstance(node, ast.FunctionDef):
                if current_module not in structure:
                    structure[current_module] = []
                structure[current_module].append(node.name)
        
        return structure
    except SyntaxError:
        return {}


def compare_code_structure(
    before: dict[Path, str],
    after: dict[Path, str],
    expected_changes: Optional[list[str]] = None,
) -> tuple[bool, list[str]]:
    """Compare before/after code structure.
    
    Args:
        before: Before refactoring code structure
        after: After refactoring code structure
        expected_changes: Optional list of expected change descriptions
        
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    
    # Extract symbols from before structure
    before_symbols = {}
    for module_path, code in before.items():
        symbols = parse_code_to_symbols(code, module_path)
        before_symbols.update(symbols)
    
    # Extract symbols from after structure
    after_symbols = {}
    for module_path, code in after.items():
        symbols = parse_code_to_symbols(code, module_path)
        after_symbols.update(symbols)
    
    # Check: no symbols lost
    before_names = set(before_symbols.keys())
    after_names = set(after_symbols.keys())
    
    lost_symbols = before_names - after_names
    if lost_symbols:
        issues.append(f"Symbols lost in refactoring: {lost_symbols}")
    
    new_symbols = after_names - before_names
    if new_symbols:
        issues.append(f"Unexpected new symbols: {new_symbols}")
    
    # Check: module names are meaningful (not generic)
    for module_path in after.keys():
        module_name = module_path.stem.lower()
        generic_names = {"module", "grouped", "extracted", "new", "two", "one"}
        if module_name in generic_names:
            issues.append(f"Generic module name: {module_name}")
    
    # Check: module names don't have redundant patterns
    for module_path in after.keys():
        module_name = module_path.stem.lower()
        if not validate_module_name(module_name):
            issues.append(f"Redundant module name: {module_name}")
    
    return len(issues) == 0, issues


def validate_module_name(module_name: str) -> bool:
    """Validate that a module name is not redundant.
    
    Checks for patterns like:
    - validation_validator.py
    - config_config.py
    - domain_domain.py
    
    Args:
        module_name: Module name to validate
        
    Returns:
        True if name is valid (not redundant), False otherwise
    """
    parts = module_name.split("_")
    
    if len(parts) == 2:
        part1, part2 = parts
        
        # Check if parts are identical
        if part1 == part2:
            return False
        
        # Check if one is a prefix of the other (redundant)
        if part1 in part2 and len(part2) - len(part1) < 3:
            return False
        if part2 in part1 and len(part1) - len(part2) < 3:
            return False
        
        # Check for known redundant patterns
        redundant_patterns = [
            ("validation", "validator"),
            ("validator", "validation"),
            ("config", "configuration"),
            ("configuration", "config"),
            ("parser", "parsing"),
            ("parsing", "parser"),
        ]
        
        for p1, p2 in redundant_patterns:
            if (p1 in part1 and p2 in part2) or (p1 in part2 and p2 in part1):
                return False
    
    return True

