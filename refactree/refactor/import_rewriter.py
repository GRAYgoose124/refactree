"""Import statement rewriting."""

import ast
from pathlib import Path


class ImportRewriter(ast.NodeTransformer):
    """Rewrites import statements in Python files."""

    def __init__(self, updates: list[tuple[str, str]]) -> None:
        """Initialize with list of (old_import, new_import) tuples."""
        self.updates = updates
        self._changes_made = 0

    @property
    def changes_made(self) -> int:
        return self._changes_made

    def rewrite_file(self, file_path: Path) -> str | None:
        """Rewrite imports in a file, return new source or None if no changes."""
        source = file_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            return None

        self._changes_made = 0
        new_tree = self.visit(tree)

        if self._changes_made > 0:
            ast.fix_missing_locations(new_tree)
            return ast.unparse(new_tree)
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        """Visit and potentially modify ImportFrom nodes."""
        if node.module is None:
            return node

        for old_import, new_import in self.updates:
            # Parse the old and new imports to extract module and names
            old_module, old_names = self._parse_from_import(old_import)
            new_module, new_names = self._parse_from_import(new_import)

            if old_module and node.module == old_module:
                # Check if any of the imported names match
                matching_aliases = []
                remaining_aliases = []

                for alias in node.names:
                    if alias.name in old_names:
                        matching_aliases.append(alias)
                    else:
                        remaining_aliases.append(alias)

                if matching_aliases:
                    self._changes_made += 1

                    # If all names are being moved, just update the module
                    if not remaining_aliases:
                        node.module = new_module
                        return node

                    # Otherwise, we need to split the import
                    # Keep the original with remaining names
                    node.names = remaining_aliases

                    # The new import will be handled by a separate pass
                    # For now, we just update in place
                    return node

        return node

    def _parse_from_import(self, import_str: str) -> tuple[str | None, set[str]]:
        """Parse 'from X import Y, Z' string into (module, {names})."""
        import_str = import_str.strip()
        if not import_str.startswith("from "):
            return None, set()

        try:
            # Remove 'from ' prefix
            rest = import_str[5:]
            parts = rest.split(" import ")
            if len(parts) != 2:
                return None, set()

            module = parts[0].strip()
            names_str = parts[1].strip()
            names = {n.strip() for n in names_str.split(",")}
            return module, names
        except (IndexError, ValueError):
            return None, set()


def update_imports_in_source(source: str, old_module: str, new_module: str, symbol_name: str) -> str:
    """Update import statements in source code.

    Handles various import patterns:
    - from old_module import symbol_name
    - from old_module import symbol_name as alias
    - from old_module import symbol_name, other_symbol
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    modified = False
    new_imports_needed: list[ast.ImportFrom] = []
    nodes_to_remove: list[ast.ImportFrom] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == old_module:
            matching = []
            remaining = []

            for alias in node.names:
                if alias.name == symbol_name:
                    matching.append(alias)
                else:
                    remaining.append(alias)

            if matching:
                modified = True

                # Create new import for the moved symbol
                new_import = ast.ImportFrom(
                    module=new_module,
                    names=matching,
                    level=node.level,
                )
                new_imports_needed.append(new_import)

                if remaining:
                    # Keep original import with remaining names
                    node.names = remaining
                else:
                    # Remove the original import entirely
                    nodes_to_remove.append(node)

    if not modified:
        return source

    # Remove empty imports and add new ones
    new_body = []
    imports_added = False

    for stmt in tree.body:
        if stmt in nodes_to_remove:
            continue

        # Add new imports after the last import statement
        if not imports_added and not isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Expr)):
            # Check if first statement is docstring
            if new_body and isinstance(new_body[0], ast.Expr):
                new_body.extend(new_imports_needed)
            else:
                new_body = new_imports_needed + new_body
            imports_added = True

        new_body.append(stmt)

    if not imports_added:
        # All statements were imports, add at the end
        new_body.extend(new_imports_needed)

    tree.body = new_body
    ast.fix_missing_locations(tree)

    return ast.unparse(tree)


def add_import_to_source(source: str, module: str, symbol_name: str, level: int = 0) -> str:
    """Add an import statement to source code if not already present."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    # Check if import already exists
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == module and node.level == level:
                if any(alias.name == symbol_name for alias in node.names):
                    return source  # Already imported
                # Add to existing import
                node.names.append(ast.alias(name=symbol_name, asname=None))
                ast.fix_missing_locations(tree)
                return ast.unparse(tree)

    # Create new import statement
    new_import = ast.ImportFrom(
        module=module,
        names=[ast.alias(name=symbol_name, asname=None)],
        level=level,
    )

    # Find insertion point (after docstring and existing imports)
    insert_idx = 0
    for i, stmt in enumerate(tree.body):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            # Skip docstring
            insert_idx = i + 1
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            insert_idx = i + 1
        else:
            break

    tree.body.insert(insert_idx, new_import)
    ast.fix_missing_locations(tree)

    return ast.unparse(tree)
