"""Refactoring plan generation."""

from pathlib import Path

from refactree.analyzer.graph import DependencyGraph
from refactree.analyzer.metrics import CouplingMetrics
from refactree.models import RefactorOperation, RefactorPlan, Symbol


class RefactorPlanner:
    """Plans refactoring operations based on analysis."""

    def __init__(
        self,
        graph: DependencyGraph,
        symbols: dict[str, Symbol],
        metrics: CouplingMetrics,
    ) -> None:
        self.graph = graph
        self.symbols = symbols
        self.metrics = metrics

    def plan_auto_organize(self, target_dir: Path | None = None) -> RefactorPlan:
        """Generate a refactoring plan based on automatic analysis.

        Uses community detection and coupling metrics to suggest optimal organization.
        """
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Get suggested moves from metrics
        suggestions = self.metrics.suggest_moves(max_suggestions=20)

        for qname, target_module, score in suggestions:
            symbol = self.symbols.get(qname)
            if not symbol:
                continue

            operation = RefactorOperation(
                symbol=symbol,
                source_module=symbol.module_path,
                target_module=target_module,
                reason=f"High coupling ({score:.1%}) with target module",
            )
            operations.append(operation)

            # Track import updates needed
            self._plan_import_updates(symbol, target_module, import_updates)

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def plan_move_symbol(
        self,
        symbol_name: str,
        target_module: Path,
        force: bool = False,
    ) -> RefactorPlan:
        """Plan to move a specific symbol to a target module."""
        # Find the symbol
        symbol = None
        for qname, sym in self.symbols.items():
            if sym.name == symbol_name or qname == symbol_name:
                symbol = sym
                break

        if not symbol:
            raise ValueError(f"Symbol '{symbol_name}' not found")

        if symbol.module_path == target_module:
            raise ValueError(f"Symbol '{symbol_name}' is already in {target_module}")

        # Check for cycles unless forced
        if not force:
            if self.graph.would_create_cycle(symbol.module_path, target_module, symbol.name):
                raise ValueError(
                    f"Moving '{symbol_name}' to {target_module} would create an import cycle"
                )

        operations = [
            RefactorOperation(
                symbol=symbol,
                source_module=symbol.module_path,
                target_module=target_module,
                reason="User requested move",
            )
        ]

        import_updates: dict[Path, list[tuple[str, str]]] = {}
        self._plan_import_updates(symbol, target_module, import_updates)

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def plan_split_module(self, module_path: Path, strategy: str = "community") -> RefactorPlan:
        """Plan to split a large module into smaller ones.

        Strategies:
        - 'community': Use community detection algorithm
        - 'class': One module per class
        - 'type': Group by type (classes, functions, constants)
        """
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Get symbols in the module
        module_symbols = [
            sym for sym in self.symbols.values()
            if sym.module_path == module_path
        ]

        if len(module_symbols) < 2:
            raise ValueError(f"Module {module_path} has too few symbols to split")

        if strategy == "community":
            groups = self._split_by_community(module_symbols)
        elif strategy == "class":
            groups = self._split_by_class(module_symbols)
        elif strategy == "type":
            groups = self._split_by_type(module_symbols)
        else:
            raise ValueError(f"Unknown split strategy: {strategy}")

        base_name = module_path.stem
        parent_dir = module_path.parent

        for i, group in enumerate(groups):
            if not group:
                continue

            # Generate target module name
            group_name = self._generate_group_name(group, base_name, i)
            target_module = parent_dir / f"{group_name}.py"

            for symbol in group:
                if symbol.module_path == target_module:
                    continue

                operations.append(
                    RefactorOperation(
                        symbol=symbol,
                        source_module=symbol.module_path,
                        target_module=target_module,
                        reason=f"Module split ({strategy} strategy)",
                    )
                )
                self._plan_import_updates(symbol, target_module, import_updates)

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def plan_merge_modules(self, source_modules: list[Path], target_module: Path) -> RefactorPlan:
        """Plan to merge multiple modules into one."""
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        for module_path in source_modules:
            if module_path == target_module:
                continue

            for symbol in self.symbols.values():
                if symbol.module_path == module_path:
                    operations.append(
                        RefactorOperation(
                            symbol=symbol,
                            source_module=module_path,
                            target_module=target_module,
                            reason="Module merge",
                        )
                    )
                    self._plan_import_updates(symbol, target_module, import_updates)

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_import_updates(
        self,
        symbol: Symbol,
        target_module: Path,
        import_updates: dict[Path, list[tuple[str, str]]],
    ) -> None:
        """Plan import statement updates for a symbol move."""
        old_import = f"from {symbol.module_path.stem} import {symbol.name}"
        new_import = f"from {target_module.stem} import {symbol.name}"

        # Find all files that import this symbol
        qname = symbol.qualified_name
        _, dependents = self.graph.get_symbol_dependencies(qname)

        for dep in dependents:
            if dep in self.symbols:
                dep_module = self.symbols[dep].module_path
                if dep_module not in import_updates:
                    import_updates[dep_module] = []
                import_updates[dep_module].append((old_import, new_import))

    def _split_by_community(self, symbols: list[Symbol]) -> list[list[Symbol]]:
        """Split symbols using community detection."""
        communities = self.graph.find_communities(resolution=1.5)

        symbol_names = {s.qualified_name for s in symbols}
        groups: list[list[Symbol]] = []

        for community in communities:
            group = [
                self.symbols[qname]
                for qname in community
                if qname in symbol_names and qname in self.symbols
            ]
            if group:
                groups.append(group)

        return groups

    def _split_by_class(self, symbols: list[Symbol]) -> list[list[Symbol]]:
        """Split so each class gets its own module."""
        from refactree.models import SymbolType

        groups: list[list[Symbol]] = []
        functions: list[Symbol] = []

        for symbol in symbols:
            if symbol.symbol_type == SymbolType.CLASS:
                groups.append([symbol])
            elif symbol.symbol_type == SymbolType.FUNCTION:
                functions.append(symbol)

        # Group standalone functions together
        if functions:
            groups.append(functions)

        return groups

    def _split_by_type(self, symbols: list[Symbol]) -> list[list[Symbol]]:
        """Split by symbol type (classes, functions, constants)."""
        from refactree.models import SymbolType

        classes = [s for s in symbols if s.symbol_type == SymbolType.CLASS]
        functions = [s for s in symbols if s.symbol_type == SymbolType.FUNCTION]
        variables = [s for s in symbols if s.symbol_type == SymbolType.VARIABLE]

        groups = []
        if classes:
            groups.append(classes)
        if functions:
            groups.append(functions)
        if variables:
            groups.append(variables)

        return groups

    def _generate_group_name(self, group: list[Symbol], base_name: str, index: int) -> str:
        """Generate a meaningful name for a group of symbols."""
        from refactree.models import SymbolType

        # If group has single class, use lowercase class name
        classes = [s for s in group if s.symbol_type == SymbolType.CLASS]
        if len(classes) == 1:
            return classes[0].name.lower()

        # If all functions, use 'utils' or 'helpers'
        if all(s.symbol_type == SymbolType.FUNCTION for s in group):
            return f"{base_name}_utils"

        # Default to indexed name
        return f"{base_name}_{index}"
