"""Coupling and cohesion metrics for code organization analysis."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from refactree.analyzer.graph import DependencyGraph
from refactree.models import EdgeType, Symbol


@dataclass
class ModuleMetrics:
    """Metrics for a single module."""

    path: Path
    symbol_count: int
    internal_edges: int  # Edges within module
    external_incoming: int  # Edges from other modules
    external_outgoing: int  # Edges to other modules
    cohesion: float  # 0-1, higher is better
    coupling: float  # 0-1, lower is better
    instability: float  # 0-1, ratio of outgoing to total external edges


@dataclass
class ProjectMetrics:
    """Aggregated metrics for the entire project."""

    total_symbols: int
    total_modules: int
    total_edges: int
    avg_cohesion: float
    avg_coupling: float
    avg_instability: float
    cycles_count: int
    largest_cycle_size: int
    module_metrics: dict[Path, ModuleMetrics]


class CouplingMetrics:
    """Calculates coupling and cohesion metrics from a dependency graph."""

    def __init__(self, graph: DependencyGraph, symbols: dict[str, Symbol]) -> None:
        self.dep_graph = graph
        self.symbols = symbols
        self._module_symbols: dict[Path, set[str]] = defaultdict(set)

        # Group symbols by module
        for qname, symbol in symbols.items():
            self._module_symbols[symbol.module_path].add(qname)

    def calculate_module_metrics(self, module_path: Path) -> ModuleMetrics:
        """Calculate metrics for a single module."""
        module_symbols = self._module_symbols.get(module_path, set())
        if not module_symbols:
            return ModuleMetrics(
                path=module_path,
                symbol_count=0,
                internal_edges=0,
                external_incoming=0,
                external_outgoing=0,
                cohesion=0.0,
                coupling=0.0,
                instability=0.5,
            )

        internal_edges = 0
        external_incoming = 0
        external_outgoing = 0

        graph = self.dep_graph.graph

        for symbol in module_symbols:
            if symbol not in graph:
                continue

            # Count outgoing edges
            for target in graph.successors(symbol):
                if target in module_symbols:
                    internal_edges += 1
                else:
                    external_outgoing += 1

            # Count incoming edges
            for source in graph.predecessors(symbol):
                if source not in module_symbols:
                    external_incoming += 1

        # Calculate cohesion: ratio of internal edges to max possible internal edges
        n = len(module_symbols)
        max_internal = n * (n - 1) if n > 1 else 1
        cohesion = internal_edges / max_internal if max_internal > 0 else 1.0

        # Calculate coupling: ratio of external edges to total edges
        total_edges = internal_edges + external_incoming + external_outgoing
        coupling = (external_incoming + external_outgoing) / total_edges if total_edges > 0 else 0.0

        # Calculate instability: Ce / (Ca + Ce)
        total_external = external_incoming + external_outgoing
        instability = external_outgoing / total_external if total_external > 0 else 0.5

        return ModuleMetrics(
            path=module_path,
            symbol_count=len(module_symbols),
            internal_edges=internal_edges,
            external_incoming=external_incoming,
            external_outgoing=external_outgoing,
            cohesion=min(cohesion, 1.0),
            coupling=min(coupling, 1.0),
            instability=instability,
        )

    def calculate_project_metrics(self) -> ProjectMetrics:
        """Calculate metrics for the entire project."""
        module_metrics = {}
        total_cohesion = 0.0
        total_coupling = 0.0
        total_instability = 0.0

        modules = list(self._module_symbols.keys())

        for module_path in modules:
            metrics = self.calculate_module_metrics(module_path)
            module_metrics[module_path] = metrics
            total_cohesion += metrics.cohesion
            total_coupling += metrics.coupling
            total_instability += metrics.instability

        n_modules = len(modules) or 1

        # Get cycle information
        cycles = list(nx.simple_cycles(self.dep_graph.graph))
        largest_cycle = max((len(c) for c in cycles), default=0)

        return ProjectMetrics(
            total_symbols=len(self.symbols),
            total_modules=len(modules),
            total_edges=self.dep_graph.graph.number_of_edges(),
            avg_cohesion=total_cohesion / n_modules,
            avg_coupling=total_coupling / n_modules,
            avg_instability=total_instability / n_modules,
            cycles_count=len(cycles),
            largest_cycle_size=largest_cycle,
            module_metrics=module_metrics,
        )

    def suggest_moves(self, max_suggestions: int = 10) -> list[tuple[str, Path, float]]:
        """Suggest symbols that could be moved to improve metrics.

        Returns list of (symbol_name, suggested_target_module, improvement_score).
        """
        suggestions = []

        for qname, symbol in self.symbols.items():
            if not symbol.is_public:
                continue

            current_module = symbol.module_path
            deps, dependents = self.dep_graph.get_symbol_dependencies(qname)

            # Count dependencies per module
            dep_modules: dict[Path, int] = defaultdict(int)
            for dep in deps:
                if dep in self.symbols:
                    dep_modules[self.symbols[dep].module_path] += 1

            # Find if symbol has more dependencies to another module
            for target_module, dep_count in dep_modules.items():
                if target_module == current_module:
                    continue

                # Score based on relative dependency count
                total_deps = len(deps)
                if total_deps == 0:
                    continue

                score = dep_count / total_deps

                # Only suggest if significant improvement
                if score > 0.5:
                    # Check if move would create cycle
                    if not self.dep_graph.would_create_cycle(current_module, target_module, symbol.name):
                        suggestions.append((qname, target_module, score))

        # Sort by improvement score and limit
        suggestions.sort(key=lambda x: x[2], reverse=True)
        return suggestions[:max_suggestions]

    def find_god_modules(self, threshold: int = 20) -> list[Path]:
        """Find modules with too many symbols (potential for splitting)."""
        return [
            path for path, symbols in self._module_symbols.items()
            if len(symbols) > threshold
        ]

    def find_highly_coupled_pairs(self, threshold: float = 0.7) -> list[tuple[Path, Path, float]]:
        """Find module pairs with high coupling."""
        pairs = []
        modules = list(self._module_symbols.keys())

        for i, mod1 in enumerate(modules):
            for mod2 in modules[i + 1:]:
                coupling = self._calculate_pairwise_coupling(mod1, mod2)
                if coupling > threshold:
                    pairs.append((mod1, mod2, coupling))

        return sorted(pairs, key=lambda x: x[2], reverse=True)

    def _calculate_pairwise_coupling(self, mod1: Path, mod2: Path) -> float:
        """Calculate coupling between two specific modules."""
        symbols1 = self._module_symbols.get(mod1, set())
        symbols2 = self._module_symbols.get(mod2, set())

        if not symbols1 or not symbols2:
            return 0.0

        edges_between = 0
        graph = self.dep_graph.graph

        for s1 in symbols1:
            if s1 not in graph:
                continue
            for neighbor in list(graph.successors(s1)) + list(graph.predecessors(s1)):
                if neighbor in symbols2:
                    edges_between += 1

        max_edges = len(symbols1) * len(symbols2) * 2
        return edges_between / max_edges if max_edges > 0 else 0.0
