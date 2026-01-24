"""Refactoring plan generation."""

from collections import defaultdict
from enum import Enum
from pathlib import Path

from refactree.analyzer.graph import DependencyGraph
from refactree.analyzer.metrics import CouplingMetrics
from refactree.models import RefactorOperation, RefactorPlan, Symbol
from refactree.semantic import SemanticAnalyzer
from refactree.preferences import UserPreferences, RuleEngine, load_preferences


class RefactorStrategy(str, Enum):
    """Refactoring strategy priorities."""

    MINIMIZE_COUPLING = "minimize-coupling"
    MAXIMIZE_COHESION = "maximize-cohesion"
    REDUCE_CYCLES = "reduce-cycles"
    CONSOLIDATE_MODULES = "consolidate-modules"
    BALANCED = "balanced"
    # Semantic strategies
    SEMANTIC_GROUPING = "semantic-grouping"
    CONCEPT_BASED = "concept-based"
    HYBRID = "hybrid"  # Structural + semantic
    PREFERENCE_WEIGHTED = "preference-weighted"
    SPLIT_LARGE_MODULES = "split-large-modules"


class RefactorPlanner:
    """Plans refactoring operations based on analysis."""

    def __init__(
        self,
        graph: DependencyGraph,
        symbols: dict[str, Symbol],
        metrics: CouplingMetrics,
        preferences: UserPreferences | None = None,
    ) -> None:
        self.graph = graph
        self.symbols = symbols
        self.metrics = metrics
        self.preferences = preferences or load_preferences()
        self.semantic_analyzer = SemanticAnalyzer(symbols) if self.preferences.semantic.enabled else None
        self.rule_engine = self._build_rule_engine()

    def plan_auto_organize(
        self,
        strategy: RefactorStrategy = RefactorStrategy.BALANCED,
        max_operations: int = 20,
        target_dir: Path | None = None,
    ) -> RefactorPlan:
        """Generate a refactoring plan based on automatic analysis.

        Uses different strategies to suggest optimal organization.
        """
        if strategy == RefactorStrategy.MINIMIZE_COUPLING:
            return self._plan_minimize_coupling(max_operations)
        elif strategy == RefactorStrategy.MAXIMIZE_COHESION:
            return self._plan_maximize_cohesion(max_operations)
        elif strategy == RefactorStrategy.REDUCE_CYCLES:
            return self._plan_reduce_cycles(max_operations)
        elif strategy == RefactorStrategy.CONSOLIDATE_MODULES:
            return self._plan_consolidate_modules(max_operations)
        elif strategy == RefactorStrategy.SEMANTIC_GROUPING:
            return self._plan_semantic_grouping(max_operations)
        elif strategy == RefactorStrategy.CONCEPT_BASED:
            return self._plan_concept_based(max_operations)
        elif strategy == RefactorStrategy.HYBRID:
            return self._plan_hybrid(max_operations)
        elif strategy == RefactorStrategy.PREFERENCE_WEIGHTED:
            return self._plan_preference_weighted(max_operations)
        elif strategy == RefactorStrategy.SPLIT_LARGE_MODULES:
            return self._plan_split_large_modules(max_operations)
        else:  # BALANCED
            return self._plan_balanced(max_operations)

    def generate_alternative_plans(
        self, max_operations_per_plan: int = 15
    ) -> dict[RefactorStrategy, RefactorPlan]:
        """Generate multiple alternative refactoring plans with different strategies."""
        plans = {}
        for strategy in RefactorStrategy:
            try:
                plan = self.plan_auto_organize(strategy, max_operations_per_plan)
                if plan.operations:  # Only include plans with operations
                    plans[strategy] = plan
            except Exception as e:
                # Log but continue - some strategies may not be applicable
                import sys
                print(f"Warning: Strategy {strategy.value} failed: {e}", file=sys.stderr)
                continue
        return plans

    def _plan_balanced(self, max_operations: int) -> RefactorPlan:
        """Balanced strategy: considers coupling, cohesion, and cycles."""
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Get suggested moves from metrics
        suggestions = self.metrics.suggest_moves(max_suggestions=max_operations * 2)

        for qname, target_module, score in suggestions:
            symbol = self.symbols.get(qname)
            if not symbol:
                continue

            # Check if move would create cycle
            if self.graph.would_create_cycle(symbol.module_path, target_module, symbol.name):
                continue

            operation = RefactorOperation(
                symbol=symbol,
                source_module=symbol.module_path,
                target_module=target_module,
                reason=f"Balanced: High coupling ({score:.1%}) with target module",
            )
            operations.append(operation)
            self._plan_import_updates(symbol, target_module, import_updates)

            if len(operations) >= max_operations:
                break

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_minimize_coupling(self, max_operations: int) -> RefactorPlan:
        """Strategy focused on minimizing inter-module coupling."""
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Get all suggestions and score by coupling reduction
        suggestions = self.metrics.suggest_moves(max_suggestions=max_operations * 3)
        scored_operations = []

        for qname, target_module, base_score in suggestions:
            symbol = self.symbols.get(qname)
            if not symbol:
                continue

            if self.graph.would_create_cycle(symbol.module_path, target_module, symbol.name):
                continue

            # Calculate coupling reduction score
            current_coupling = self._estimate_coupling_reduction(symbol, target_module)
            scored_operations.append((symbol, target_module, current_coupling, base_score))

        # Sort by coupling reduction (descending)
        scored_operations.sort(key=lambda x: x[2], reverse=True)

        for symbol, target_module, coupling_score, base_score in scored_operations[:max_operations]:
            operation = RefactorOperation(
                symbol=symbol,
                source_module=symbol.module_path,
                target_module=target_module,
                reason=f"Minimize coupling: reduces coupling by {coupling_score:.1%}",
            )
            operations.append(operation)
            self._plan_import_updates(symbol, target_module, import_updates)

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_maximize_cohesion(self, max_operations: int) -> RefactorPlan:
        """Strategy focused on maximizing intra-module cohesion."""
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        suggestions = self.metrics.suggest_moves(max_suggestions=max_operations * 3)
        scored_operations = []

        for qname, target_module, base_score in suggestions:
            symbol = self.symbols.get(qname)
            if not symbol:
                continue

            if self.graph.would_create_cycle(symbol.module_path, target_module, symbol.name):
                continue

            # Calculate cohesion improvement
            cohesion_gain = self._estimate_cohesion_gain(symbol, target_module)
            scored_operations.append((symbol, target_module, cohesion_gain, base_score))

        # Sort by cohesion gain (descending)
        scored_operations.sort(key=lambda x: x[2], reverse=True)

        for symbol, target_module, cohesion_gain, base_score in scored_operations[:max_operations]:
            operation = RefactorOperation(
                symbol=symbol,
                source_module=symbol.module_path,
                target_module=target_module,
                reason=f"Maximize cohesion: improves cohesion by {cohesion_gain:.1%}",
            )
            operations.append(operation)
            self._plan_import_updates(symbol, target_module, import_updates)

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_reduce_cycles(self, max_operations: int) -> RefactorPlan:
        """Strategy focused on breaking circular dependencies."""
        import networkx as nx

        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Find symbols involved in cycles
        cycles = list(nx.simple_cycles(self.graph.graph))
        cycle_symbols = set()
        for cycle in cycles:
            cycle_symbols.update(cycle)

        suggestions = self.metrics.suggest_moves(max_suggestions=max_operations * 3)
        cycle_breaking_ops = []

        for qname, target_module, base_score in suggestions:
            if qname not in cycle_symbols:
                continue

            symbol = self.symbols.get(qname)
            if not symbol:
                continue

            # Check if this move would break a cycle by checking if it prevents cycle formation
            if not self.graph.would_create_cycle(symbol.module_path, target_module, symbol.name):
                # Additional check: see if target is not in any cycle with source
                source_in_cycles = any(symbol.module_path.stem in str(c) for c in cycles)
                if source_in_cycles:
                    cycle_breaking_ops.append((symbol, target_module, base_score))

        # Sort by base score
        cycle_breaking_ops.sort(key=lambda x: x[2], reverse=True)

        for symbol, target_module, score in cycle_breaking_ops[:max_operations]:
            operation = RefactorOperation(
                symbol=symbol,
                source_module=symbol.module_path,
                target_module=target_module,
                reason=f"Reduce cycles: breaks circular dependency",
            )
            operations.append(operation)
            self._plan_import_updates(symbol, target_module, import_updates)

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_consolidate_modules(self, max_operations: int) -> RefactorPlan:
        """Strategy focused on consolidating related symbols into fewer modules.
        
        Only consolidates when:
        - Modules are highly coupled (structural dependency)
        - Modules are semantically related (same domain/concept)
        - Consolidation creates logical boundaries
        - Resulting module size is reasonable (< 20 symbols)
        """
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Calculate module sizes
        module_sizes: dict[Path, int] = {}
        module_symbols: dict[Path, list[Symbol]] = {}
        for symbol in self.symbols.values():
            module_sizes[symbol.module_path] = module_sizes.get(symbol.module_path, 0) + 1
            if symbol.module_path not in module_symbols:
                module_symbols[symbol.module_path] = []
            module_symbols[symbol.module_path].append(symbol)

        # Find highly coupled module pairs with reasonable threshold
        coupled_pairs = self.metrics.find_highly_coupled_pairs(threshold=0.5)  # Higher threshold for real coupling
        
        # Filter and score consolidation candidates
        consolidation_candidates: list[tuple[Path, Path, float]] = []
        
        for mod1, mod2, coupling_score in coupled_pairs:
            # Skip if modules are too large (don't create huge files)
            size1 = module_sizes.get(mod1, 0)
            size2 = module_sizes.get(mod2, 0)
            combined_size = size1 + size2
            
            if combined_size > 20:  # Don't consolidate if result > 20 symbols
                continue
            
            # Both modules should be reasonably small for consolidation
            if size1 > 15 or size2 > 15:
                continue
            
            # Check semantic similarity if available
            semantic_score = 0.0
            if self.semantic_analyzer:
                symbols1 = module_symbols.get(mod1, [])
                symbols2 = module_symbols.get(mod2, [])
                
                if symbols1 and symbols2:
                    # Calculate average semantic similarity between modules
                    similarities = []
                    for sym1 in symbols1[:5]:  # Sample to avoid O(n²)
                        for sym2 in symbols2[:5]:
                            from refactree.semantic.similarity import calculate_semantic_similarity
                            sim = calculate_semantic_similarity(sym1, sym2)
                            similarities.append(sim)
                    
                    if similarities:
                        semantic_score = sum(similarities) / len(similarities)
            
            # Combined score: coupling + semantic similarity
            # Require at least moderate semantic similarity if available
            if self.semantic_analyzer and semantic_score < 0.4:
                continue  # Skip if not semantically related
            
            # Prefer consolidating into module with better name or more symbols
            # (but not if it's a main/entry point like cli.py, main.py)
            target = mod1
            source = mod2
            
            mod1_name = mod1.stem.lower()
            mod2_name = mod2.stem.lower()
            
            # Don't consolidate INTO cli/main/__init__ files (they're entry points or package markers)
            entry_point_names = {"cli", "main", "__main__", "__init__"}
            
            if mod1_name in entry_point_names:
                if mod2_name in entry_point_names:
                    continue  # Skip if both are entry points
                target = mod2
                source = mod1
            elif mod2_name in entry_point_names:
                target = mod1
                source = mod2
            elif size1 < size2:
                # Prefer smaller target (consolidate into smaller)
                target = mod1
                source = mod2
            else:
                target = mod2
                source = mod1
            
            # Additional check: don't consolidate if target is already large
            if module_sizes.get(target, 0) > 15:
                continue
            
            # Check if they're in the same logical directory (same parent)
            # This respects package boundaries - prefer same package consolidation
            same_package = target.parent == source.parent
            if not same_package:
                # Only consolidate across packages if VERY highly coupled AND semantically similar
                if coupling_score < 0.75 or (self.semantic_analyzer and semantic_score < 0.6):
                    continue
            
            # Additional safeguard: check if modules share a common concept/domain
            if self.semantic_analyzer:
                symbols1 = module_symbols.get(mod1, [])
                symbols2 = module_symbols.get(mod2, [])
                
                if symbols1 and symbols2:
                    # Check if they share common concepts
                    info1 = self.semantic_analyzer.analyze_symbol(symbols1[0])
                    info2 = self.semantic_analyzer.analyze_symbol(symbols2[0])
                    
                    shared_concepts = set(info1.concepts) & set(info2.concepts)
                    if not shared_concepts and semantic_score < 0.5:
                        continue  # No shared concepts and low similarity - skip
            
            # Combined score
            combined_score = (coupling_score * 0.6) + (semantic_score * 0.4) if self.semantic_analyzer else coupling_score
            
            consolidation_candidates.append((source, target, combined_score))
        
        # Sort by score (best candidates first)
        consolidation_candidates.sort(key=lambda x: x[2], reverse=True)
        
        # Apply consolidations
        consolidated_sources = set()
        for source_module, target_module, score in consolidation_candidates[:max_operations]:
            if source_module in consolidated_sources:
                continue
            
            # Double-check final size
            final_size = module_sizes.get(target_module, 0) + module_sizes.get(source_module, 0)
            if final_size > 20:
                continue
            
            # Move symbols from source to target
            moved_count = 0
            for symbol in module_symbols.get(source_module, []):
                # Check for cycles
                if self.graph.would_create_cycle(source_module, target_module, symbol.name):
                    continue
                
                operation = RefactorOperation(
                    symbol=symbol,
                    source_module=source_module,
                    target_module=target_module,
                    reason=f"Consolidate: highly coupled ({score:.1%}) and semantically related modules",
                )
                operations.append(operation)
                self._plan_import_updates(symbol, target_module, import_updates)
                moved_count += 1
                
                if len(operations) >= max_operations:
                    break
            
            if moved_count > 0:
                consolidated_sources.add(source_module)
            
            if len(operations) >= max_operations:
                break

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _estimate_coupling_reduction(self, symbol: Symbol, target_module: Path) -> float:
        """Estimate how much coupling would be reduced by moving symbol."""
        current_module = symbol.module_path
        deps, dependents = self.graph.get_symbol_dependencies(symbol.qualified_name)

        # Count external dependencies that would become internal
        external_to_internal = sum(
            1
            for dep in deps
            if dep in self.symbols
            and self.symbols[dep].module_path == target_module
            and self.symbols[dep].module_path != current_module
        )

        total_external = sum(
            1
            for dep in deps
            if dep in self.symbols and self.symbols[dep].module_path != current_module
        )

        return external_to_internal / total_external if total_external > 0 else 0.0

    def _estimate_cohesion_gain(self, symbol: Symbol, target_module: Path) -> float:
        """Estimate how much cohesion would improve by moving symbol."""
        current_module = symbol.module_path
        deps, dependents = self.graph.get_symbol_dependencies(symbol.qualified_name)

        # Count dependencies that would become internal
        would_be_internal = sum(
            1
            for dep in deps
            if dep in self.symbols and self.symbols[dep].module_path == target_module
        )

        total_deps = len(deps)
        return would_be_internal / total_deps if total_deps > 0 else 0.0


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

    def _build_rule_engine(self) -> RuleEngine:
        """Build rule engine from user preferences."""
        from refactree.preferences.rules import RuleEngine, OrganizationalRule, SemanticTag
        from pathlib import Path

        engine = RuleEngine()

        # Add rules from preferences
        for rule_config in self.preferences.rules:
            rule = OrganizationalRule(
                name=rule_config.name,
                pattern=rule_config.pattern,
                target_module=Path(rule_config.target_module),
                priority=rule_config.priority,
            )
            engine.add_rule(rule)

        # Add tags from preferences
        for tag_config in self.preferences.tags:
            tag = SemanticTag(
                name=tag_config.name,
                keywords=tag_config.keywords,
                target_module=Path(tag_config.target_module),
            )
            engine.add_tag(tag)

        return engine

    def _plan_semantic_grouping(self, max_operations: int) -> RefactorPlan:
        """Strategy focused on semantic similarity grouping.
        
        Enhanced to respect code conventions and only suggest moves that create
        better boundaries without breaking existing structure.
        """
        if not self.semantic_analyzer:
            # Fallback to balanced if semantic analysis disabled
            return self._plan_balanced(max_operations)

        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Find semantic groups
        threshold = self.preferences.semantic.similarity_threshold
        groups = self.semantic_analyzer.find_semantic_groups(
            similarity_threshold=threshold,
            min_group_size=2,
        )

        # Create operations for each group
        for group in groups[:max_operations]:
            if not group.suggested_module:
                continue

            # Skip if all symbols should preserve location
            if all(
                self.semantic_analyzer.convention_detector.should_preserve_location(sym)
                for sym in group.symbols
            ):
                continue

            # Only suggest moves that create better boundaries
            # Don't move if target is same as source or would break structure
            for symbol in group.symbols:
                if symbol.module_path == group.suggested_module:
                    continue

                # Respect code conventions - don't move CLI commands, tests, entry points
                if self.semantic_analyzer.convention_detector.should_preserve_location(
                    symbol
                ):
                    continue

                # Don't move into entry point files
                target_name = group.suggested_module.stem.lower()
                if target_name in {"cli", "main", "__main__"}:
                    continue

                # Check for cycles
                if self.graph.would_create_cycle(
                    symbol.module_path, group.suggested_module, symbol.name
                ):
                    continue

                # Only suggest if it creates a meaningful boundary
                # (e.g., moving to a domain-specific module, not just any module)
                source_dir = symbol.module_path.parent
                target_dir = group.suggested_module.parent

                # Prefer moves that create new focused modules or move to appropriate domain
                operation = RefactorOperation(
                    symbol=symbol,
                    source_module=symbol.module_path,
                    target_module=group.suggested_module,
                    reason=f"Semantic grouping: {group.concept} (similarity: {group.similarity_score:.1%})",
                )
                operations.append(operation)
                self._plan_import_updates(symbol, group.suggested_module, import_updates)

                if len(operations) >= max_operations:
                    break

            if len(operations) >= max_operations:
                break

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_concept_based(self, max_operations: int) -> RefactorPlan:
        """Strategy that organizes by extracted concepts/topics.
        
        Enhanced to use meaningful domain and functionality concepts rather than
        generic keywords, and respect code conventions.
        """
        if not self.semantic_analyzer:
            return self._plan_balanced(max_operations)

        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Analyze all symbols
        semantic_info = self.semantic_analyzer.analyze_symbols()

        # Group by meaningful concepts (domain + functionality)
        # First pass: group by domain, then by functionality within domain
        domain_groups: dict[str, list[Symbol]] = {}
        functionality_groups: dict[str, list[Symbol]] = {}
        
        for qname, info in semantic_info.items():
            symbol = self.symbols[qname]

            # Extract domain and functionality
            domain = self.semantic_analyzer.convention_detector.extract_domain(
                symbol, info.keywords
            )
            functionality = (
                self.semantic_analyzer.convention_detector.extract_functionality(
                    symbol
                )
            )

            # Group by domain first (primary grouping)
            if domain:
                if domain not in domain_groups:
                    domain_groups[domain] = []
                domain_groups[domain].append(symbol)
            # Also group by functionality if no domain found
            elif functionality:
                if functionality not in functionality_groups:
                    functionality_groups[functionality] = []
                functionality_groups[functionality].append(symbol)
        
        # Merge groups: prefer domain groups, use functionality as fallback
        concept_groups: dict[str, list[Symbol]] = {}
        
        # Add domain groups (these take precedence)
        for domain, symbols in domain_groups.items():
            # Use domain as the concept name
            concept_groups[domain] = symbols
        
        # Add functionality groups for symbols not in domain groups
        for functionality, symbols in functionality_groups.items():
            # Check if any of these symbols are already in a domain group
            ungrouped = [
                s for s in symbols
                if not any(s in domain_groups.get(d, []) for d in domain_groups)
            ]
            if ungrouped:
                concept_groups[functionality] = ungrouped

        # Sort concepts by group size (larger groups first)
        sorted_concepts = sorted(
            concept_groups.items(), key=lambda x: len(x[1]), reverse=True
        )

        # Create operations for concept-based grouping
        for concept, symbols in sorted_concepts[:max_operations]:
            if len(symbols) < 2:
                continue

            # Filter out symbols that should preserve location
            filtered_symbols = [
                s
                for s in symbols
                if not self.semantic_analyzer.convention_detector.should_preserve_location(
                    s
                )
            ]

            if len(filtered_symbols) < 2:
                continue

            # Suggest module based on concept
            suggested_module = self.semantic_analyzer._suggest_module_name(
                filtered_symbols, concept
            )
            if not suggested_module:
                continue

            # Don't create modules with generic names
            module_name = suggested_module.stem.lower()
            generic_names = {"module", "grouped", "extracted", "new", "two", "one"}
            if module_name in generic_names:
                continue

            for symbol in filtered_symbols:
                if symbol.module_path == suggested_module:
                    continue

                # Don't move into entry point files
                target_name = suggested_module.stem.lower()
                if target_name in {"cli", "main", "__main__"}:
                    continue

                if self.graph.would_create_cycle(
                    symbol.module_path, suggested_module, symbol.name
                ):
                    continue

                operation = RefactorOperation(
                    symbol=symbol,
                    source_module=symbol.module_path,
                    target_module=suggested_module,
                    reason=f"Concept-based: {concept}",
                )
                operations.append(operation)
                self._plan_import_updates(symbol, suggested_module, import_updates)

                if len(operations) >= max_operations:
                    break

            if len(operations) >= max_operations:
                break

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_hybrid(self, max_operations: int) -> RefactorPlan:
        """Strategy that combines structural and semantic analysis."""
        semantic_weight = self.preferences.semantic.weight
        structural_weight = 1.0 - semantic_weight

        # Get structural suggestions
        structural_plan = self._plan_balanced(max_operations)

        # Get semantic suggestions
        if self.semantic_analyzer:
            semantic_plan = self._plan_semantic_grouping(max_operations)
        else:
            semantic_plan = RefactorPlan(operations=[], import_updates={}, validation_required=True)

        # Combine operations with weighted scoring
        all_operations: dict[str, tuple[RefactorOperation, float]] = {}

        # Add structural operations
        for op in structural_plan.operations:
            key = op.symbol.qualified_name
            all_operations[key] = (op, structural_weight)

        # Add/update with semantic operations
        for op in semantic_plan.operations:
            key = op.symbol.qualified_name
            if key in all_operations:
                # Combine: use semantic target if higher weight
                if semantic_weight > structural_weight:
                    all_operations[key] = (op, semantic_weight)
            else:
                all_operations[key] = (op, semantic_weight)

        # Sort by combined score and take top operations
        sorted_ops = sorted(all_operations.values(), key=lambda x: x[1], reverse=True)
        selected_ops = [op for op, _ in sorted_ops[:max_operations]]

        # Rebuild import updates
        import_updates: dict[Path, list[tuple[str, str]]] = {}
        for op in selected_ops:
            self._plan_import_updates(op.symbol, op.target_module, import_updates)

        return RefactorPlan(
            operations=selected_ops,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_preference_weighted(self, max_operations: int) -> RefactorPlan:
        """Strategy that applies user-defined rules and preferences."""
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Get semantic info for tag matching
        semantic_info = {}
        if self.semantic_analyzer:
            semantic_info = self.semantic_analyzer.analyze_symbols()

        # Apply rules and tags to all symbols
        for symbol in self.symbols.values():
            # Get keywords for tag matching
            keywords = []
            if symbol.qualified_name in semantic_info:
                keywords = semantic_info[symbol.qualified_name].keywords

            # Check rule engine for suggestions
            suggested_target = self.rule_engine.suggest_target(symbol, keywords)

            if suggested_target and suggested_target != symbol.module_path:
                # Check for cycles
                if self.graph.would_create_cycle(symbol.module_path, suggested_target, symbol.name):
                    continue

                operation = RefactorOperation(
                    symbol=symbol,
                    source_module=symbol.module_path,
                    target_module=suggested_target,
                    reason="User preference/rule",
                )
                operations.append(operation)
                self._plan_import_updates(symbol, suggested_target, import_updates)

                if len(operations) >= max_operations:
                    break

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )

    def _plan_split_large_modules(self, max_operations: int) -> RefactorPlan:
        """Identify and split large modules into focused ones.
        
        This strategy focuses on breaking down large files (>15 symbols) into
        smaller, more focused modules based on semantic analysis and logical boundaries.
        """
        operations: list[RefactorOperation] = []
        import_updates: dict[Path, list[tuple[str, str]]] = {}

        # Find large modules
        large_modules = self.metrics.find_god_modules(threshold=15)

        if not large_modules:
            return RefactorPlan(
                operations=[],
                import_updates={},
                validation_required=True,
            )

        # Process each large module
        for module_path in large_modules[:max_operations // 5]:  # Limit modules to process
            # Get all symbols in this module
            module_symbols = [
                s for s in self.symbols.values() if s.module_path == module_path
            ]

            if len(module_symbols) < 15:
                continue  # Skip if somehow below threshold now

            # Find logical split points using semantic analysis
            semantic_info = {}
            all_groups: list[list[Symbol]] = []
            
            if self.semantic_analyzer:
                # Use semantic grouping to find related symbols
                groups = self.semantic_analyzer.find_semantic_groups(
                    module_symbols,
                    similarity_threshold=0.5,  # Moderate threshold for splitting
                    min_group_size=2,
                )

                # Also try concept-based grouping
                semantic_info = self.semantic_analyzer.analyze_symbols(module_symbols)

                # Group by domain and functionality
                domain_groups: dict[str, list[Symbol]] = defaultdict(list)
                functionality_groups: dict[str, list[Symbol]] = defaultdict(list)

                for symbol in module_symbols:
                    info = semantic_info.get(symbol.qualified_name)
                    if info:
                        # Group by domain
                        for concept in info.concepts:
                            if concept in [
                                "auth",
                                "user",
                                "payment",
                                "validation",
                                "parsing",
                                "analysis",
                                "semantic",
                                "project",
                                "config",
                            ]:
                                domain_groups[concept].append(symbol)
                                break

                        # Group by functionality
                        for concept in info.concepts:
                            if concept in [
                                "validator",
                                "parser",
                                "handler",
                                "service",
                                "manager",
                                "analyzer",
                                "metrics",
                            ]:
                                functionality_groups[concept].append(symbol)
                                break

                # Add semantic groups
                for group in groups:
                    if len(group.symbols) >= 2:
                        all_groups.append(group.symbols)

                # Add domain groups
                for domain_symbols in domain_groups.values():
                    if len(domain_symbols) >= 2 and domain_symbols not in all_groups:
                        all_groups.append(domain_symbols)

                # Add functionality groups
                for func_symbols in functionality_groups.values():
                    if len(func_symbols) >= 2 and func_symbols not in all_groups:
                        all_groups.append(func_symbols)

            else:
                # Fallback: use community detection
                all_groups = self._split_by_community(module_symbols)

            # Create operations for each group
            for group in all_groups:
                if len(group) < 2:
                    continue

                # Skip if group contains symbols that should stay (CLI, tests, etc.)
                if any(
                    self.semantic_analyzer.convention_detector.should_preserve_location(sym)
                    if self.semantic_analyzer
                    else False
                    for sym in group
                ):
                    continue

                # Suggest module name
                concept = "extracted"
                if self.semantic_analyzer and semantic_info:
                    # Get concepts from group
                    group_concepts = set()
                    for sym in group:
                        info = semantic_info.get(sym.qualified_name)
                        if info:
                            group_concepts.update(info.concepts)

                    # Use most relevant concept
                    if group_concepts:
                        concept = list(group_concepts)[0]
                    suggested_module = self.semantic_analyzer._suggest_module_name(
                        group, concept
                    )
                else:
                    # Fallback naming
                    base_name = module_path.stem
                    suggested_module = module_path.parent / f"{base_name}_extracted.py"

                if not suggested_module or suggested_module == module_path:
                    continue

                # Move symbols to new module
                for symbol in group:
                    if self.graph.would_create_cycle(
                        module_path, suggested_module, symbol.name
                    ):
                        continue

                    operation = RefactorOperation(
                        symbol=symbol,
                        source_module=module_path,
                        target_module=suggested_module,
                        reason=f"Split large module: extract {concept} functionality",
                    )
                    operations.append(operation)
                    self._plan_import_updates(symbol, suggested_module, import_updates)

                    if len(operations) >= max_operations:
                        break

                if len(operations) >= max_operations:
                    break

            if len(operations) >= max_operations:
                break

        return RefactorPlan(
            operations=operations,
            import_updates=import_updates,
            validation_required=True,
        )
