"""Turn a partition into a named, ordered module plan with interface metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from refactree.decompose.classsplit import ClassSplit, split_classes
from refactree.decompose.cluster import ClusterConfig, partition
from refactree.decompose.graph import UnitGraph, Weights, build_graph
from refactree.decompose.naming import name_modules
from refactree.decompose.units import Unit, UnitKind, extract_units


@dataclass
class ModulePlan:
    name: str
    units: list[int]  # unit indices, source order
    lines: int
    defines: set[str]
    imports_from: dict[str, set[str]] = field(default_factory=dict)  # sibling -> names
    type_imports_from: dict[str, set[str]] = field(default_factory=dict)  # TYPE_CHECKING only
    # names only needed when functions run, from modules imported later: bottom-of-file
    deferred_imports_from: dict[str, set[str]] = field(default_factory=dict)
    cohesion: float = 0.0


@dataclass
class DecompositionPlan:
    source: str
    units: list[Unit]
    graph: UnitGraph
    modules: list[ModulePlan]  # dependency order: leaves first
    main_units: list[int]
    dunder_units: list[int]
    docstring: str | None
    modularity: float
    class_splits: list[ClassSplit] = field(default_factory=list)

    @property
    def interface_width(self) -> int:
        """Total number of names crossing module boundaries (at runtime)."""
        return sum(
            len(ns)
            for m in self.modules
            for d in (m.imports_from, m.deferred_imports_from)
            for ns in d.values()
        )

    @property
    def exports(self) -> set[str]:
        """Public names the generated package re-exports (the original's public surface)."""
        return {
            n for m in self.modules for n in m.defines - self.graph.deleted if not n.startswith("_")
        }

    def module_of(self, name: str) -> str | None:
        for m in self.modules:
            if name in m.defines:
                return m.name
        return None


def build_plan(
    source: str, cfg: ClusterConfig | None = None, weights: Weights | None = None
) -> DecompositionPlan:
    cfg = cfg or ClusterConfig()
    splits: list[ClassSplit] = []
    if cfg.split_classes:
        source, splits = split_classes(source, cfg.max_lines)
    units, doc = extract_units(source)
    if cfg.min_lines < 0:  # auto: scale with the file
        code_lines = sum(u.lines for u in units if u.kind in (UnitKind.DEF, UnitKind.ASSIGN))
        cfg.min_lines = max(10, min(40, code_lines // 25))
    ug = build_graph(units, weights)
    parts, q = partition(ug, cfg)

    # order modules so dependencies come first
    where = {g: k for k, p in enumerate(parts) for g in p}
    # import order must respect import-time edges; among the rest, follow all
    # dependencies as far as their (possibly cyclic) structure allows
    full: nx.DiGraph[int] = nx.DiGraph()
    full.add_nodes_from(range(len(parts)))
    cg: nx.DiGraph[int] = nx.DiGraph()
    cg.add_nodes_from(range(len(parts)))
    for a, b in ug.deps.edges:
        if where[a] != where[b]:
            full.add_edge(where[b], where[a])  # b before a
    for a, b in ug.eager.edges:
        if where[a] != where[b]:
            cg.add_edge(where[b], where[a])
    cond = nx.condensation(full)
    rank = {
        k: (pos, min(parts[k]))
        for pos, c in enumerate(nx.lexicographical_topological_sort(cond, key=lambda c: c))
        for k in cond.nodes[c]["members"]
    }
    order = list(nx.lexicographical_topological_sort(cg, key=lambda k: rank[k]))

    external = set(ug.external)
    names = name_modules(ug, parts, external | set(ug.definer))

    modules: list[ModulePlan] = []
    for k in order:
        idxs = sorted(i for g in parts[k] for i in ug.groups[g])
        defines = set().union(*(units[i].defines for i in idxs)) if idxs else set()
        internal = sum(
            d["weight"] for a, b, d in ug.affinity.edges(parts[k], data=True) if b in parts[k]
        )
        boundary = sum(
            d["weight"] for a, b, d in ug.affinity.edges(parts[k], data=True) if b not in parts[k]
        )
        modules.append(
            ModulePlan(
                names[k],
                idxs,
                sum(units[i].lines for i in idxs),
                defines,
                cohesion=internal / (internal + boundary) if internal + boundary else 1.0,
            )
        )

    position = {m.name: k for k, m in enumerate(modules)}
    for m in modules:
        runtime = {n for i in m.units for n in units[i].runtime_uses}
        used = {n for i in m.units for n in units[i].uses}
        mine = {ug.group_of[i] for i in m.units}
        eager_targets = {h for g in mine for h in ug.eager.successors(g)}
        for n in used - m.defines:
            g = ug.definer.get(n)
            if g is None:
                continue
            src = names[where[g]]
            if n not in runtime:
                target = m.type_imports_from
            elif g not in eager_targets and position[src] > position[m.name]:
                target = m.deferred_imports_from
            else:
                target = m.imports_from
            target.setdefault(src, set()).add(n)

    main_units = [u.idx for u in units if u.kind == UnitKind.MAIN]
    dunder_units = [u.idx for u in units if u.kind == UnitKind.DUNDER]
    return DecompositionPlan(source, units, ug, modules, main_units, dunder_units, doc, q, splits)
