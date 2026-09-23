"""Turn a partition into a named, ordered module plan with interface metrics."""

from __future__ import annotations

import ast
import keyword
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

import networkx as nx

from refactree.decompose.cluster import ClusterConfig, partition
from refactree.decompose.graph import STOP_TOKENS, UnitGraph, Weights, build_graph, split_identifier
from refactree.decompose.units import Unit, UnitKind, extract_units


@dataclass
class ModulePlan:
    name: str
    units: list[int]  # unit indices, source order
    lines: int
    defines: set[str]
    imports_from: dict[str, set[str]] = field(default_factory=dict)  # sibling -> names
    type_imports_from: dict[str, set[str]] = field(default_factory=dict)  # TYPE_CHECKING only
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

    @property
    def interface_width(self) -> int:
        """Total number of names crossing module boundaries."""
        return sum(len(ns) for m in self.modules for ns in m.imports_from.values())

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


def _snake(name: str) -> str:
    return "_".join(split_identifier(name)) or name.lower()


_RESERVED = set(sys.stdlib_module_names) | {"__main__", "__init__", "test", "tests"}


def _name_module(ug: UnitGraph, part: set[int], taken: set[str], avoid: set[str]) -> str:
    units = ug.units
    total = sum(ug.group_lines[g] for g in part)
    # a dominant class names its module
    biggest = max(
        (units[i] for g in part for i in ug.groups[g] if isinstance(units[i].node, ast.ClassDef)),
        key=lambda u: u.lines,
        default=None,
    )
    cands: list[str] = []
    sec_lines: Counter[str] = Counter()
    for g in part:
        for i in ug.groups[g]:
            if units[i].section:
                sec_lines[units[i].section] += units[i].lines
    if sec_lines:
        sec, n = sec_lines.most_common(1)[0]
        if n >= 0.6 * total and len(split_identifier(sec)) <= 3:
            cands.append("_".join(split_identifier(sec)))
    if biggest is not None and biggest.lines >= 0.5 * total:
        cands.append(_snake(next(iter(biggest.defines))).strip("_"))
    tokens: Counter[str] = Counter()
    for g in part:
        # centrality within the module: how often siblings use this group
        fan_in = len(set(ug.deps.predecessors(g)) | set(ug.affinity[g])) + 1
        for i in ug.groups[g]:
            for ident in units[i].defines:
                for t in set(split_identifier(ident)):
                    if t not in STOP_TOKENS and len(t) > 2:
                        tokens[t] += 2 + fan_in
        # section banners ("# --- reporting ---") are the author's own module names
        for i in ug.groups[g]:
            for t in {*units[i].comment_tokens, *split_identifier(units[i].section)}:
                if t not in STOP_TOKENS and len(t) > 2:
                    tokens[t] += 4
    ranked = [t for t, _ in tokens.most_common()]
    cands += ranked[:1]
    if len(ranked) > 1:
        cands.append(f"{ranked[0]}_{ranked[1]}")
    if any("main" in units[i].defines for g in part for i in ug.groups[g]):
        cands.insert(0, "cli")
    cands.append("core")
    for c in cands:
        c = re.sub(r"\W", "_", c).strip("_") or "core"
        if c in _RESERVED or c in avoid or keyword.iskeyword(c):
            c = f"{c}_ops"
        if c not in taken:
            return c
    base = cands[-1]
    k = 2
    while f"{base}{k}" in taken:
        k += 1
    return f"{base}{k}"


def build_plan(
    source: str, cfg: ClusterConfig | None = None, weights: Weights | None = None
) -> DecompositionPlan:
    cfg = cfg or ClusterConfig()
    units, doc = extract_units(source)
    if cfg.min_lines < 0:  # auto: scale with the file
        code_lines = sum(u.lines for u in units if u.kind in (UnitKind.DEF, UnitKind.ASSIGN))
        cfg.min_lines = max(10, min(40, code_lines // 25))
    ug = build_graph(units, weights)
    parts, q = partition(ug, cfg)

    # order modules so dependencies come first
    where = {g: k for k, p in enumerate(parts) for g in p}
    cg: nx.DiGraph[int] = nx.DiGraph()
    cg.add_nodes_from(range(len(parts)))
    for a, b in ug.deps.edges:
        if where[a] != where[b]:
            cg.add_edge(where[b], where[a])  # b before a
    order = list(nx.lexicographical_topological_sort(cg, key=lambda k: min(parts[k])))

    external = set(ug.external)
    taken: set[str] = set()
    names: dict[int, str] = {}
    for k in sorted(order, key=lambda k: -sum(ug.group_lines[g] for g in parts[k])):
        is_const = len(parts) > 1 and all(
            units[i].kind == UnitKind.ASSIGN
            and all(n.lstrip("_").isupper() for n in units[i].defines)
            for g in parts[k]
            for i in ug.groups[g]
        )
        nm = "constants" if is_const and "constants" not in taken else None
        names[k] = nm or _name_module(ug, parts[k], taken, external)
        taken.add(names[k])

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

    for m in modules:
        runtime = {n for i in m.units for n in units[i].runtime_uses}
        used = {n for i in m.units for n in units[i].uses}
        for n in used - m.defines:
            g = ug.definer.get(n)
            if g is not None:
                target = m.imports_from if n in runtime else m.type_imports_from
                target.setdefault(names[where[g]], set()).add(n)

    main_units = [u.idx for u in units if u.kind == UnitKind.MAIN]
    dunder_units = [u.idx for u in units if u.kind == UnitKind.DUNDER]
    return DecompositionPlan(source, units, ug, modules, main_units, dunder_units, doc, q)
