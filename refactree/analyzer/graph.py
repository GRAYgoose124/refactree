"""Dependency graph construction and analysis."""

from collections import defaultdict
from pathlib import Path

import networkx as nx

from refactree.models import AnalysisResult, Dependency, EdgeType, Symbol


class DependencyGraph:
    """Builds and analyzes a dependency graph from parsed symbols."""

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self._symbols: dict[str, Symbol] = {}
        self._modules: dict[Path, list[str]] = defaultdict(list)

    def build(self, symbols: dict[str, Symbol], dependencies: list[Dependency]) -> None:
        """Build the dependency graph from symbols and dependencies."""
        self._symbols = symbols
        self.graph.clear()

        # Add nodes for all symbols
        for qname, symbol in symbols.items():
            self.graph.add_node(
                qname,
                symbol_type=symbol.symbol_type.value,
                module=str(symbol.module_path),
                line_start=symbol.line_start,
                line_end=symbol.line_end,
                is_public=symbol.is_public,
            )
            self._modules[symbol.module_path].append(symbol.name)

        # Add edges for dependencies
        for dep in dependencies:
            # Try to resolve the target to a qualified name
            target_qname = self._resolve_target(dep.target, dep.source)

            self.graph.add_edge(
                dep.source,
                target_qname,
                edge_type=dep.edge_type.value,
                line=dep.line,
                weight=dep.weight,
            )

    def _resolve_target(self, target: str, source: str) -> str:
        """Resolve a target name to its qualified name if possible."""
        # If target is already qualified and exists, return as-is
        if target in self._symbols:
            return target

        # Try to find the target in the same module as source
        if "." in source:
            module = source.rsplit(".", 1)[0]
            candidate = f"{module}.{target}"
            if candidate in self._symbols:
                return candidate

        # Return original target (might be external dependency)
        return target

    def get_analysis_result(self) -> AnalysisResult:
        """Return a complete analysis result."""
        # Build import graph (module-level)
        import_graph: dict[str, set[str]] = defaultdict(set)
        for source, target, data in self.graph.edges(data=True):
            if data.get("edge_type") == EdgeType.IMPORTS.value:
                src_module = source.rsplit(".", 1)[0] if "." in source else source
                tgt_module = target.rsplit(".", 1)[0] if "." in target else target
                if src_module != tgt_module:
                    import_graph[src_module].add(tgt_module)

        # Detect cycles
        cycles = list(nx.simple_cycles(self.graph))

        # Convert dependencies from graph edges
        dependencies = [
            Dependency(
                source=src,
                target=tgt,
                edge_type=EdgeType(data["edge_type"]),
                line=data["line"],
                weight=data.get("weight", 1.0),
            )
            for src, tgt, data in self.graph.edges(data=True)
        ]

        return AnalysisResult(
            symbols=self._symbols,
            dependencies=dependencies,
            modules=dict(self._modules),
            import_graph=dict(import_graph),
            cycles=cycles,
        )

    def find_strongly_connected_components(self) -> list[set[str]]:
        """Find strongly connected components (potential modules)."""
        return [set(c) for c in nx.strongly_connected_components(self.graph)]

    def find_communities(self, resolution: float = 1.0) -> list[set[str]]:
        """Find communities using Louvain algorithm for module suggestions."""
        undirected = self.graph.to_undirected()
        if len(undirected.nodes()) == 0:
            return []

        try:
            communities = nx.community.louvain_communities(
                undirected,
                weight="weight",
                resolution=resolution,
            )
            return [set(c) for c in communities]
        except Exception:
            # Fallback if Louvain fails
            return [set(nx.descendants(self.graph, n) | {n}) for n in self.graph.nodes() if self.graph.in_degree(n) == 0]

    def get_symbol_dependencies(self, symbol_name: str) -> tuple[set[str], set[str]]:
        """Get direct dependencies (outgoing) and dependents (incoming) for a symbol."""
        if symbol_name not in self.graph:
            return set(), set()

        dependencies = set(self.graph.successors(symbol_name))
        dependents = set(self.graph.predecessors(symbol_name))
        return dependencies, dependents

    def get_transitive_dependencies(self, symbol_name: str) -> set[str]:
        """Get all transitive dependencies of a symbol."""
        if symbol_name not in self.graph:
            return set()
        return set(nx.descendants(self.graph, symbol_name))

    def would_create_cycle(self, source_module: Path, target_module: Path, symbol: str) -> bool:
        """Check if moving a symbol would create an import cycle."""
        # Create a hypothetical graph to test
        test_graph = self.graph.copy()

        # Simulate the move by updating edges
        old_qname = f"{source_module.stem}.{symbol}"
        new_qname = f"{target_module.stem}.{symbol}"

        if old_qname in test_graph:
            # Update all edges pointing to/from the old name
            for pred in list(test_graph.predecessors(old_qname)):
                data = test_graph.edges[pred, old_qname]
                test_graph.add_edge(pred, new_qname, **data)
            for succ in list(test_graph.successors(old_qname)):
                data = test_graph.edges[old_qname, succ]
                test_graph.add_edge(new_qname, succ, **data)
            test_graph.remove_node(old_qname)

        # Check for cycles
        try:
            nx.find_cycle(test_graph)
            return True
        except nx.NetworkXNoCycle:
            return False
