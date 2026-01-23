"""Tests for the analyzer module."""

from pathlib import Path
import tempfile

import pytest

from refactree.analyzer import ASTParser, DependencyGraph
from refactree.models import SymbolType, EdgeType


def test_parse_simple_class():
    """Test parsing a simple class definition."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_module.py"
        test_file.write_text('''
class MyClass:
    """A simple class."""

    def method(self):
        pass
''')
        parser = ASTParser(Path(tmpdir))
        symbols, deps = parser.parse_file(test_file)

        assert len(symbols) == 1
        assert symbols[0].name == "MyClass"
        assert symbols[0].symbol_type == SymbolType.CLASS
        assert symbols[0].docstring == "A simple class."


def test_parse_function():
    """Test parsing a function definition."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "funcs.py"
        test_file.write_text('''
def my_function(x: int) -> str:
    """Convert int to string."""
    return str(x)
''')
        parser = ASTParser(Path(tmpdir))
        symbols, deps = parser.parse_file(test_file)

        assert len(symbols) == 1
        assert symbols[0].name == "my_function"
        assert symbols[0].symbol_type == SymbolType.FUNCTION


def test_parse_inheritance():
    """Test parsing class inheritance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "inheritance.py"
        test_file.write_text('''
class Base:
    pass

class Child(Base):
    pass
''')
        parser = ASTParser(Path(tmpdir))
        symbols, deps = parser.parse_file(test_file)

        assert len(symbols) == 2

        inheritance_deps = [d for d in deps if d.edge_type == EdgeType.INHERITS]
        assert len(inheritance_deps) == 1
        assert inheritance_deps[0].target == "Base"


def test_dependency_graph_build():
    """Test building a dependency graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "module.py"
        test_file.write_text('''
class A:
    pass

class B(A):
    pass
''')
        parser = ASTParser(Path(tmpdir))
        symbols, deps = parser.parse_project()

        graph = DependencyGraph()
        graph.build(symbols, deps)

        result = graph.get_analysis_result()
        assert len(result.symbols) == 2
        assert len(result.cycles) == 0


def test_parse_imports():
    """Test parsing import statements."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "imports.py"
        test_file.write_text('''
from pathlib import Path
from typing import List, Dict

def process(items: List[str]) -> Dict[str, int]:
    pass
''')
        parser = ASTParser(Path(tmpdir))
        symbols, deps = parser.parse_file(test_file)

        import_deps = [d for d in deps if d.edge_type == EdgeType.IMPORTS]
        assert len(import_deps) >= 2
