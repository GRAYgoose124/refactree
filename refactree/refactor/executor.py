"""Refactoring execution with transaction support."""

import ast
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from refactree.models import RefactorPlan, Symbol
from refactree.refactor.import_rewriter import add_import_to_source, update_imports_in_source


@dataclass
class FileTransaction:
    """Represents a file modification that can be committed or rolled back."""

    path: Path
    original_content: str | None  # None if file didn't exist
    new_content: str
    committed: bool = False


@dataclass
class TransactionLog:
    """Log of all file transactions for rollback support."""

    transactions: list[FileTransaction] = field(default_factory=list)
    backup_dir: Path | None = None

    def add(self, path: Path, new_content: str) -> None:
        """Add a file transaction."""
        original = path.read_text(encoding="utf-8") if path.exists() else None
        self.transactions.append(
            FileTransaction(path=path, original_content=original, new_content=new_content)
        )

    def commit_all(self) -> None:
        """Commit all transactions (write files)."""
        for txn in self.transactions:
            txn.path.parent.mkdir(parents=True, exist_ok=True)
            txn.path.write_text(txn.new_content, encoding="utf-8")
            txn.committed = True

    def rollback(self) -> None:
        """Rollback all committed transactions."""
        for txn in reversed(self.transactions):
            if txn.committed:
                if txn.original_content is None:
                    # File was created, delete it
                    if txn.path.exists():
                        txn.path.unlink()
                else:
                    # Restore original content
                    txn.path.write_text(txn.original_content, encoding="utf-8")
                txn.committed = False


class RefactorExecutor:
    """Executes refactoring plans with transaction support."""

    def __init__(
        self,
        project_root: Path,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.project_root = project_root
        self.on_progress = on_progress or (lambda _: None)
        self._transaction_log: TransactionLog | None = None

    def execute(self, plan: RefactorPlan, dry_run: bool = False) -> list[Path]:
        """Execute a refactoring plan.

        Args:
            plan: The refactoring plan to execute
            dry_run: If True, only simulate changes without writing

        Returns:
            List of modified file paths
        """
        self._transaction_log = TransactionLog()
        modified_files: list[Path] = []

        try:
            # Phase 1: Extract symbols from source files
            self.on_progress("Extracting symbols from source files...")
            symbol_sources = self._extract_symbols(plan)

            # Phase 2: Build new module contents
            self.on_progress("Building target module contents...")
            module_contents = self._build_module_contents(plan, symbol_sources)

            # Phase 3: Update source files (remove moved symbols)
            self.on_progress("Updating source files...")
            source_updates = self._update_source_files(plan)

            # Phase 4: Update imports in all affected files
            self.on_progress("Updating import statements...")
            import_updates = self._update_imports(plan)

            # Merge all updates
            all_updates = {**module_contents, **source_updates, **import_updates}

            # Add all transactions
            for path, content in all_updates.items():
                self._transaction_log.add(path, content)
                modified_files.append(path)

            if not dry_run:
                # Commit all changes
                self.on_progress("Writing changes to disk...")
                self._transaction_log.commit_all()

            return modified_files

        except Exception as e:
            # Rollback on any error
            if self._transaction_log:
                self.on_progress("Error occurred, rolling back changes...")
                self._transaction_log.rollback()
            raise RuntimeError(f"Refactoring failed: {e}") from e

    def rollback(self) -> None:
        """Rollback the last executed plan."""
        if self._transaction_log:
            self._transaction_log.rollback()

    def _extract_symbols(self, plan: RefactorPlan) -> dict[str, str]:
        """Extract symbol source code from files.

        Returns dict mapping qualified_name to source code.
        """
        symbol_sources: dict[str, str] = {}

        for op in plan.operations:
            source_file = op.source_module
            if not source_file.exists():
                continue

            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source)

            for node in tree.body:
                if self._node_matches_symbol(node, op.symbol):
                    # Extract the source code for this symbol
                    lines = source.splitlines(keepends=True)
                    start = op.symbol.line_start - 1
                    end = op.symbol.line_end
                    symbol_source = "".join(lines[start:end])
                    symbol_sources[op.symbol.qualified_name] = symbol_source
                    break

        return symbol_sources

    def _node_matches_symbol(self, node: ast.AST, symbol: Symbol) -> bool:
        """Check if an AST node matches a symbol."""
        if isinstance(node, ast.ClassDef) and symbol.name == node.name:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and symbol.name == node.name:
            return True
        return False

    def _build_module_contents(
        self,
        plan: RefactorPlan,
        symbol_sources: dict[str, str],
    ) -> dict[Path, str]:
        """Build contents for target modules."""
        module_contents: dict[Path, str] = {}

        # Group operations by target module
        ops_by_target: dict[Path, list] = {}
        for op in plan.operations:
            if op.target_module not in ops_by_target:
                ops_by_target[op.target_module] = []
            ops_by_target[op.target_module].append(op)

        for target_module, ops in ops_by_target.items():
            # Start with existing content or empty
            if target_module.exists():
                content = target_module.read_text(encoding="utf-8")
            else:
                content = '"""Module created by refactree."""\n\n'

            # Add each symbol
            for op in ops:
                qname = op.symbol.qualified_name
                if qname in symbol_sources:
                    symbol_source = symbol_sources[qname]

                    # Add necessary imports for the symbol's dependencies
                    # This is a simplified version - full implementation would
                    # analyze the symbol's AST for dependencies
                    content = content.rstrip() + "\n\n\n" + symbol_source

            module_contents[target_module] = content.strip() + "\n"

        return module_contents

    def _update_source_files(self, plan: RefactorPlan) -> dict[Path, str]:
        """Update source files by removing moved symbols."""
        source_updates: dict[Path, str] = {}

        # Group operations by source module
        ops_by_source: dict[Path, list] = {}
        for op in plan.operations:
            if op.source_module not in ops_by_source:
                ops_by_source[op.source_module] = []
            ops_by_source[op.source_module].append(op)

        for source_module, ops in ops_by_source.items():
            if not source_module.exists():
                continue

            source = source_module.read_text(encoding="utf-8")
            tree = ast.parse(source)

            # Collect names to remove
            names_to_remove = {op.symbol.name for op in ops}

            # Filter out removed nodes
            new_body = []
            for node in tree.body:
                should_keep = True
                if isinstance(node, ast.ClassDef) and node.name in names_to_remove:
                    should_keep = False
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names_to_remove:
                    should_keep = False

                if should_keep:
                    new_body.append(node)

            tree.body = new_body
            ast.fix_missing_locations(tree)

            # Only update if there's remaining content
            new_source = ast.unparse(tree)
            if new_source.strip():
                source_updates[source_module] = new_source
            else:
                # Module is now empty, could be deleted
                # For safety, leave a minimal module
                source_updates[source_module] = '"""Module emptied by refactree refactoring."""\n'

        return source_updates

    def _update_imports(self, plan: RefactorPlan) -> dict[Path, str]:
        """Update import statements in affected files."""
        import_updates: dict[Path, str] = {}

        for file_path, updates in plan.import_updates.items():
            if not file_path.exists():
                continue

            source = file_path.read_text(encoding="utf-8")

            for old_import, new_import in updates:
                # Parse old and new imports
                old_module = self._extract_module_from_import(old_import)
                new_module = self._extract_module_from_import(new_import)
                symbol_name = self._extract_name_from_import(old_import)

                if old_module and new_module and symbol_name:
                    source = update_imports_in_source(source, old_module, new_module, symbol_name)

            import_updates[file_path] = source

        return import_updates

    def _extract_module_from_import(self, import_str: str) -> str | None:
        """Extract module name from 'from X import Y' string."""
        if not import_str.startswith("from "):
            return None
        parts = import_str[5:].split(" import ")
        return parts[0].strip() if parts else None

    def _extract_name_from_import(self, import_str: str) -> str | None:
        """Extract symbol name from 'from X import Y' string."""
        parts = import_str.split(" import ")
        if len(parts) < 2:
            return None
        return parts[1].strip().split(",")[0].strip()
