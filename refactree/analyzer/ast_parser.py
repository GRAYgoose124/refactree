"""AST parsing and symbol extraction."""

import ast
from pathlib import Path

from refactree.models import Dependency, EdgeType, Symbol, SymbolType


class ASTParser:
    """Parses Python files and extracts symbols and dependencies."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._current_module: Path | None = None
        self._current_class: str | None = None
        self._symbols: dict[str, Symbol] = {}
        self._dependencies: list[Dependency] = []

    def parse_file(self, file_path: Path) -> tuple[list[Symbol], list[Dependency]]:
        """Parse a single Python file and extract symbols and dependencies."""
        self._current_module = file_path
        self._symbols = {}
        self._dependencies = []

        source = file_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            raise ValueError(f"Syntax error in {file_path}: {e}") from e

        # Add parent references for context tracking
        self._add_parent_refs(tree)

        # First pass: collect all definitions
        self._collect_definitions(tree, file_path)

        # Second pass: analyze dependencies
        self._analyze_dependencies(tree, file_path)

        return list(self._symbols.values()), self._dependencies

    def parse_project(self) -> tuple[dict[str, Symbol], list[Dependency]]:
        """Parse all Python files in the project."""
        all_symbols: dict[str, Symbol] = {}
        all_dependencies: list[Dependency] = []

        for py_file in self.project_root.rglob("*.py"):
            # Skip hidden directories and common non-source dirs
            if any(part.startswith(".") or part in {"__pycache__", "venv", ".venv", "node_modules"}
                   for part in py_file.parts):
                continue

            try:
                symbols, deps = self.parse_file(py_file)
                for sym in symbols:
                    all_symbols[sym.qualified_name] = sym
                all_dependencies.extend(deps)
            except (ValueError, OSError) as e:
                # Log but continue parsing other files
                print(f"Warning: Could not parse {py_file}: {e}")

        return all_symbols, all_dependencies

    def _add_parent_refs(self, node: ast.AST, parent: ast.AST | None = None) -> None:
        """Add parent references to all AST nodes."""
        node._parent = parent  # type: ignore[attr-defined]
        for child in ast.iter_child_nodes(node):
            self._add_parent_refs(child, node)

    def _collect_definitions(self, tree: ast.Module, file_path: Path) -> None:
        """Collect all class, function, and top-level variable definitions."""
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._process_class(node, file_path)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                self._process_function(node, file_path)
            elif isinstance(node, ast.Assign | ast.AnnAssign):
                self._process_assignment(node, file_path)

    def _process_class(self, node: ast.ClassDef, file_path: Path) -> None:
        """Process a class definition."""
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(ast.unparse(base))

        decorators = [ast.unparse(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)

        symbol = Symbol(
            name=node.name,
            symbol_type=SymbolType.CLASS,
            module_path=file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=docstring,
            decorators=decorators,
            bases=bases,
            is_public=not node.name.startswith("_"),
        )
        self._symbols[symbol.qualified_name] = symbol

        # Process methods within the class
        old_class = self._current_class
        self._current_class = node.name
        for child in node.body:
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                self._process_method(child, file_path, node.name)
        self._current_class = old_class

    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, file_path: Path) -> None:
        """Process a top-level function definition."""
        decorators = [ast.unparse(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)

        symbol = Symbol(
            name=node.name,
            symbol_type=SymbolType.FUNCTION,
            module_path=file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=docstring,
            decorators=decorators,
            is_public=not node.name.startswith("_"),
        )
        self._symbols[symbol.qualified_name] = symbol

    def _process_method(self, node: ast.FunctionDef | ast.AsyncFunctionDef, file_path: Path, class_name: str) -> None:
        """Process a method within a class (for dependency tracking, not as separate symbol)."""
        # Methods are tracked as part of their class, but we analyze their dependencies
        pass

    def _process_assignment(self, node: ast.Assign | ast.AnnAssign, file_path: Path) -> None:
        """Process a top-level assignment (module-level variable)."""
        if isinstance(node, ast.AnnAssign) and node.target:
            if isinstance(node.target, ast.Name):
                name = node.target.id
                # Only track if it looks like a constant (ALL_CAPS) or type alias
                if name.isupper() or (node.annotation and not name.startswith("_")):
                    symbol = Symbol(
                        name=name,
                        symbol_type=SymbolType.VARIABLE,
                        module_path=file_path,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                        is_public=not name.startswith("_"),
                    )
                    self._symbols[symbol.qualified_name] = symbol

    def _analyze_dependencies(self, tree: ast.Module, file_path: Path) -> None:
        """Analyze all dependencies in the module."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self._process_import(node, file_path)
            elif isinstance(node, ast.ImportFrom):
                self._process_import_from(node, file_path)
            elif isinstance(node, ast.ClassDef):
                self._process_class_dependencies(node, file_path)
            elif isinstance(node, ast.Call):
                self._process_call(node, file_path)

    def _process_import(self, node: ast.Import, file_path: Path) -> None:
        """Process import statement."""
        module_name = file_path.stem
        for alias in node.names:
            self._dependencies.append(
                Dependency(
                    source=module_name,
                    target=alias.name,
                    edge_type=EdgeType.IMPORTS,
                    line=node.lineno,
                )
            )

    def _process_import_from(self, node: ast.ImportFrom, file_path: Path) -> None:
        """Process from ... import statement."""
        module_name = file_path.stem
        if node.module:
            for alias in node.names:
                target = f"{node.module}.{alias.name}" if alias.name != "*" else node.module
                self._dependencies.append(
                    Dependency(
                        source=module_name,
                        target=target,
                        edge_type=EdgeType.IMPORTS,
                        line=node.lineno,
                    )
                )

    def _process_class_dependencies(self, node: ast.ClassDef, file_path: Path) -> None:
        """Process class inheritance and type annotations."""
        class_qname = f"{file_path.stem}.{node.name}"

        # Inheritance
        for base in node.bases:
            if isinstance(base, ast.Name):
                self._dependencies.append(
                    Dependency(
                        source=class_qname,
                        target=base.id,
                        edge_type=EdgeType.INHERITS,
                        line=node.lineno,
                        weight=2.0,  # Inheritance is a strong coupling
                    )
                )

    def _process_call(self, node: ast.Call, file_path: Path) -> None:
        """Process function/method calls."""
        # Get the enclosing function or class
        source = self._get_enclosing_scope(node, file_path)
        if not source:
            source = file_path.stem

        if isinstance(node.func, ast.Name):
            # Direct call like ClassName() or function_name()
            target = node.func.id
            # Heuristic: capitalized names are likely class instantiations
            edge_type = EdgeType.INSTANTIATES if target[0].isupper() else EdgeType.CALLS
            self._dependencies.append(
                Dependency(
                    source=source,
                    target=target,
                    edge_type=edge_type,
                    line=node.lineno,
                )
            )

    def _get_enclosing_scope(self, node: ast.AST, file_path: Path) -> str | None:
        """Get the qualified name of the enclosing class or function."""
        current = node
        while hasattr(current, "_parent"):
            current = current._parent  # type: ignore[attr-defined]
            if isinstance(current, ast.ClassDef):
                return f"{file_path.stem}.{current.name}"
            if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
                # Check if this function is inside a class
                if hasattr(current, "_parent") and isinstance(current._parent, ast.ClassDef):  # type: ignore[attr-defined]
                    return f"{file_path.stem}.{current._parent.name}"  # type: ignore[attr-defined]
                return f"{file_path.stem}.{current.name}"
        return None
