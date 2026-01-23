"""Core data models for refactree."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SymbolType(Enum):
    """Type of Python symbol."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    VARIABLE = "variable"
    IMPORT = "import"


class EdgeType(Enum):
    """Type of dependency edge."""

    IMPORTS = "imports"
    INHERITS = "inherits"
    CALLS = "calls"
    INSTANTIATES = "instantiates"
    TYPE_REFERENCE = "type_reference"
    ATTRIBUTE_ACCESS = "attribute_access"


@dataclass
class Symbol:
    """Represents a Python symbol (class, function, variable, etc.)."""

    name: str
    symbol_type: SymbolType
    module_path: Path
    line_start: int
    line_end: int
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)  # For classes
    is_public: bool = True

    @property
    def qualified_name(self) -> str:
        """Return fully qualified name including module."""
        module_name = self.module_path.stem
        return f"{module_name}.{self.name}"


@dataclass
class Dependency:
    """Represents a dependency between two symbols."""

    source: str  # Qualified name of source symbol
    target: str  # Qualified name or import path of target
    edge_type: EdgeType
    line: int  # Line where dependency occurs
    weight: float = 1.0  # For weighted graph algorithms


@dataclass
class RefactorOperation:
    """Represents a single refactoring operation."""

    symbol: Symbol
    source_module: Path
    target_module: Path
    reason: str


@dataclass
class RefactorPlan:
    """A complete refactoring plan with multiple operations."""

    operations: list[RefactorOperation]
    import_updates: dict[Path, list[tuple[str, str]]]  # file -> [(old_import, new_import)]
    validation_required: bool = True

    @property
    def affected_files(self) -> set[Path]:
        """Return all files affected by this plan."""
        files = set()
        for op in self.operations:
            files.add(op.source_module)
            files.add(op.target_module)
        files.update(self.import_updates.keys())
        return files


@dataclass
class AnalysisResult:
    """Result of analyzing a Python project."""

    symbols: dict[str, Symbol]  # qualified_name -> Symbol
    dependencies: list[Dependency]
    modules: dict[Path, list[str]]  # module_path -> list of symbol names
    import_graph: dict[str, set[str]]  # module -> set of imported modules
    cycles: list[list[str]]  # Detected circular dependencies
