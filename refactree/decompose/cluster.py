"""Partition the unit graph into modules: high cohesion, narrow & acyclic interfaces."""

from __future__ import annotations

import ast
from dataclasses import dataclass

import networkx as nx
from networkx.algorithms.community import louvain_communities, modularity

from refactree.decompose.graph import UnitGraph
from refactree.decompose.units import UnitKind


@dataclass
class ClusterConfig:
    resolution: float = 1.5
    min_lines: int = -1  # -1: auto (scales with file size)
    max_lines: int = 400
    extract_constants: bool = True
    interface_penalty: float = 1.0  # λ: cost of each name crossing a module boundary
    refine_sweeps: int = 8
    seed: int = 0


Partition = list[set[int]]


def _cluster_digraph(ug: UnitGraph, parts: Partition) -> nx.DiGraph[int]:
    where = {g: k for k, p in enumerate(parts) for g in p}
    cg: nx.DiGraph[int] = nx.DiGraph()
    cg.add_nodes_from(range(len(parts)))
    for a, b in ug.deps.edges:
        if where[a] != where[b]:
            cg.add_edge(where[a], where[b])
    return cg


def _lines(ug: UnitGraph, part: set[int]) -> int:
    return sum(ug.group_lines[g] for g in part)


def _cycle_badness(ug: UnitGraph, parts: Partition) -> tuple[int, int]:
    """(#clusters caught in cycles, #dependency edges inside those cycles)."""
    where = {g: k for k, p in enumerate(parts) for g in p}
    cg = _cluster_digraph(ug, parts)
    comp: dict[int, int] = {}
    n_clusters = 0
    for ci, scc in enumerate(nx.strongly_connected_components(cg)):
        if len(scc) > 1:
            n_clusters += len(scc)
            for k in scc:
                comp[k] = ci
    edges = sum(
        1
        for a, b in ug.deps.edges
        if where[a] != where[b] and where[a] in comp and comp[where[a]] == comp.get(where[b])
    )
    return n_clusters, edges


def _affinity_to(ug: UnitGraph, g: int, part: set[int]) -> float:
    return float(sum(d["weight"] for h, d in ug.affinity[g].items() if h in part and h != g))


def repair_cycles(ug: UnitGraph, parts: Partition) -> Partition:
    """Break import cycles by relocating single groups, choosing the move that loses the
    least affinity; fall back to merging when no single move helps."""
    parts = [set(p) for p in parts if p]
    while True:
        bad = _cycle_badness(ug, parts)
        if bad == (0, 0):
            return parts
        where = {g: k for k, p in enumerate(parts) for g in p}
        cg = _cluster_digraph(ug, parts)
        sccs = [scc for scc in nx.strongly_connected_components(cg) if len(scc) > 1]
        in_scc = {k: i for i, scc in enumerate(sccs) for k in scc}
        movers = {
            x
            for a, b in ug.deps.edges
            if where[a] != where[b] and in_scc.get(where[a], -1) == in_scc.get(where[b], -2)
            for x in (a, b)
        }
        pushed = _push_down(ug, parts, sccs, where, bad)
        if pushed is not None:
            parts = pushed
            continue
        best: tuple[tuple[int, int], float, Partition] | None = None
        for g in movers:
            src = where[g]
            if len(parts[src]) == 1:
                continue
            stay = _affinity_to(ug, g, parts[src])
            for t in [*sccs[in_scc[src]], -1]:
                if t == src:
                    continue
                trial = [set(p) for p in parts]
                trial[src].discard(g)
                if t == -1:
                    trial.append({g})
                    gain = 0.0
                else:
                    trial[t].add(g)
                    gain = _affinity_to(ug, g, parts[t])
                nb = _cycle_badness(ug, trial)
                if nb >= bad:
                    continue
                cand = (nb, stay - gain, trial)
                if best is None or (cand[1], cand[0]) < (best[1], best[0]):
                    best = cand
        if best is None:
            return make_acyclic(ug, parts)
        parts = [p for p in best[2] if p]


def _push_down(
    ug: UnitGraph,
    parts: Partition,
    sccs: list[set[int]],
    where: dict[int, int],
    bad: tuple[int, int],
) -> Partition | None:
    """For clusters A, B in a cycle, move the targets of B->A edges (plus their dependency
    closure inside A) into B, or vice versa; take the cheapest option that reduces badness."""
    best: tuple[float, Partition] | None = None
    for scc in sccs:
        cross: dict[tuple[int, int], set[int]] = {}
        for a, b in ug.deps.edges:
            ka, kb = where[a], where[b]
            if ka != kb and ka in scc and kb in scc:
                cross.setdefault((ka, kb), set()).add(b)
        for (src, dst), targets in cross.items():
            # src uses `targets` living in dst: move them (and what they need in dst) into src
            closure = set(targets)
            stack = list(targets)
            while stack:
                x = stack.pop()
                for y in ug.deps.successors(x):
                    if where[y] == dst and y not in closure:
                        closure.add(y)
                        stack.append(y)
            if closure == parts[dst]:
                continue
            trial = [set(p) for p in parts]
            trial[dst] -= closure
            trial[src] |= closure
            nb = _cycle_badness(ug, trial)
            if nb >= bad:
                continue
            cost = sum(_affinity_to(ug, g, parts[dst] - closure) for g in closure) - sum(
                _affinity_to(ug, g, parts[src]) for g in closure
            )
            if best is None or cost < best[0]:
                best = (cost, trial)
    return [p for p in best[1] if p] if best else None


def make_acyclic(ug: UnitGraph, parts: Partition) -> Partition:
    """Merge clusters that participate in import cycles."""
    cg = _cluster_digraph(ug, parts)
    out: Partition = []
    for scc in nx.strongly_connected_components(cg):
        out.append(set().union(*(parts[k] for k in scc)))
    return out


def _is_acyclic(ug: UnitGraph, parts: Partition) -> bool:
    return nx.is_directed_acyclic_graph(_cluster_digraph(ug, parts))


def split_oversized(
    ug: UnitGraph, parts: Partition, cfg: ClusterConfig, frozen: set[frozenset[int]]
) -> Partition:
    out: Partition = []
    for k, p in enumerate(parts):
        if _lines(ug, p) <= cfg.max_lines or len(p) < 2 or frozenset(p) in frozen:
            out.append(p)
            continue
        sub = ug.affinity.subgraph(p)
        res = cfg.resolution
        pieces: Partition = [p]
        for _ in range(8):
            res *= 1.6
            pieces = [set(c) for c in louvain_communities(sub, "weight", res, seed=cfg.seed)]
            pieces = _absorb_crumbs(ug, pieces, cfg.min_lines)
            if len(pieces) > 1:
                break
        trial = [*out, *pieces, *parts[k + 1 :]]
        # worthwhile if it meaningfully shrinks the module (an atomic giant class may
        # keep it above max_lines regardless) or improves the objective outright
        solves = max(_lines(ug, x) for x in pieces) <= max(cfg.max_lines, 0.8 * _lines(ug, p))
        helps = objective(ug, trial, cfg) > objective(ug, [*out, p, *parts[k + 1 :]], cfg)
        if len(pieces) > 1 and (solves or helps) and _is_acyclic(ug, trial):
            out.extend(pieces)
        else:
            frozen.add(frozenset(p))
            out.append(p)
    return out


def _absorb_crumbs(ug: UnitGraph, pieces: Partition, min_lines: int) -> Partition:
    """Fold pieces below min_lines into their most affine sibling piece."""
    pieces = sorted((set(x) for x in pieces), key=lambda x: _lines(ug, x))
    while len(pieces) > 1 and _lines(ug, pieces[0]) < min_lines:
        crumb = pieces.pop(0)
        best = max(pieces, key=lambda q: sum(_affinity_to(ug, g, q) for g in crumb))
        best |= crumb
        pieces.sort(key=lambda x: _lines(ug, x))
    return pieces


def merge_small(ug: UnitGraph, parts: Partition, cfg: ClusterConfig) -> Partition:
    parts = [set(p) for p in parts]
    stuck: set[frozenset[int]] = set()
    while True:
        small = [
            k
            for k, p in enumerate(parts)
            if _lines(ug, p) < cfg.min_lines and frozenset(p) not in stuck
        ]
        if not small or len(parts) == 1:
            return parts
        k = min(small, key=lambda k: _lines(ug, parts[k]))
        p = parts[k]
        conn: dict[int, float] = {}
        for j, q in enumerate(parts):
            if j == k:
                continue
            w = sum(ug.affinity[a][b]["weight"] for a in p for b in ug.affinity[a] if b in q)
            if w > 0:
                conn[j] = w
        merged = False
        hosts = sorted(
            (j for j in range(len(parts)) if j != k),
            key=lambda j: (-conn.get(j, 0.0), _lines(ug, parts[j])),
        )
        for j in hosts:
            trial = [q for i, q in enumerate(parts) if i not in (j, k)] + [parts[j] | p]
            if _is_acyclic(ug, trial):
                parts = trial
                merged = True
                break
        if not merged:
            stuck.add(frozenset(p))


def _is_pure_constant(ug: UnitGraph, g: int, constants: set[int]) -> bool:
    for i in ug.groups[g]:
        u = ug.units[i]
        if u.kind != UnitKind.ASSIGN or not isinstance(u.node, ast.Assign | ast.AnnAssign):
            return False
        if not all(n.isupper() or n.lstrip("_").isupper() for n in u.defines):
            return False
        for n in u.uses:
            h = ug.definer.get(n)
            if h is not None and h != g and h not in constants:
                return False
    return True


def extract_constants(ug: UnitGraph, parts: Partition, min_lines: int = 0) -> Partition:
    where = {g: k for k, p in enumerate(parts) for g in p}
    constants: set[int] = set()
    changed = True
    while changed:  # fixpoint: constants built from constants
        changed = False
        for g in ug.deps.nodes:
            if g in constants or not _is_pure_constant(ug, g, constants):
                continue
            users = {where[u] for u in ug.deps.predecessors(g)} - {where[g]}
            if users:
                constants.add(g)
                changed = True
    # constants referenced from at most one foreign cluster are better left alone
    shared = {
        g
        for g in constants
        if len({where[u] for u in ug.deps.predecessors(g) if u not in constants}) >= 2
    }
    closure = set(shared)
    for g in shared:
        closure |= nx.descendants(ug.deps, g) & constants
    if not closure or _lines(ug, closure) < min_lines:
        return parts
    out = [p - closure for p in parts]
    return [p for p in out if p] + [closure]


def _objective_terms(ug: UnitGraph) -> list[tuple[int, str, int]]:
    """(user group, name, defining group) triples: every potential interface crossing."""
    out = []
    for g, members in enumerate(ug.groups):
        for n in {n for i in members for n in ug.units[i].uses}:
            h = ug.definer.get(n)
            if h is not None and h != g:
                out.append((g, n, h))
    return out


def objective(ug: UnitGraph, parts: Partition, cfg: ClusterConfig) -> float:
    """Cohesion (resolution-scaled modularity) minus normalized interface width."""
    q = modularity(ug.affinity, parts, weight="weight", resolution=cfg.resolution)
    terms = _objective_terms(ug)
    return q - cfg.interface_penalty * _iface(parts, terms) / max(1, len(terms))


def _iface(parts: Partition, terms: list[tuple[int, str, int]]) -> int:
    where = {g: k for k, p in enumerate(parts) for g in p}
    return len({(where[g], n) for g, n, h in terms if where[g] != where[h]})


def refine(ug: UnitGraph, parts: Partition, cfg: ClusterConfig) -> Partition:
    """Greedy single-group moves that improve cohesion - λ·interface, keeping imports acyclic
    and modules under max_lines."""
    aff = ug.affinity
    m2 = 2.0 * aff.size(weight="weight")
    if m2 == 0:
        return parts
    terms = _objective_terms(ug)
    norm = cfg.interface_penalty / max(1, len(terms))
    deg = dict(aff.degree(weight="weight"))
    parts = [set(p) for p in parts]
    for _ in range(cfg.refine_sweeps):
        improved = False
        for g in sorted(aff.nodes):
            where = {x: k for k, p in enumerate(parts) for x in p}
            a = where[g]
            if len(parts[a]) == 1:
                continue
            tot = [sum(deg[x] for x in p) for p in parts]
            k_to = [0.0] * len(parts)
            for h, d in aff[g].items():
                if h != g:
                    k_to[where[h]] += d["weight"]
            base_iface = _iface(parts, terms)
            neighbours = {where[h] for h in aff[g]} | {where[h] for h in ug.deps[g]}
            best: tuple[float, int] | None = None
            for b in neighbours - {a}:
                if _lines(ug, parts[b]) + ug.group_lines[g] > cfg.max_lines:
                    continue
                dq = (k_to[b] - k_to[a]) / (m2 / 2) - cfg.resolution * deg[g] * (
                    tot[b] - (tot[a] - deg[g])
                ) / (m2 * m2 / 2)
                trial = [set(p) for p in parts]
                trial[a].discard(g)
                trial[b].add(g)
                delta = dq - norm * (_iface(trial, terms) - base_iface)
                if delta > 1e-9 and (best is None or delta > best[0]) and _is_acyclic(ug, trial):
                    best = (delta, b)
            if best is not None:
                parts[a].discard(g)
                parts[best[1]].add(g)
                improved = True
        parts = [p for p in parts if p]
        if not improved:
            break
    return parts


def merge_pass(ug: UnitGraph, parts: Partition, cfg: ClusterConfig) -> Partition:
    """Greedily merge whole clusters while that improves the objective."""
    parts = [set(p) for p in parts]
    while len(parts) > 1:
        base = objective(ug, parts, cfg)
        where = {g: k for k, p in enumerate(parts) for g in p}
        pairs = {
            (min(where[a], where[b]), max(where[a], where[b]))
            for a, b in ug.affinity.edges
            if where[a] != where[b]
        }
        best: tuple[float, Partition] | None = None
        for i, j in pairs:
            if _lines(ug, parts[i]) + _lines(ug, parts[j]) > cfg.max_lines:
                continue
            trial = [p for k, p in enumerate(parts) if k not in (i, j)] + [parts[i] | parts[j]]
            gain = objective(ug, trial, cfg) - base
            if gain > 1e-9 and (best is None or gain > best[0]) and _is_acyclic(ug, trial):
                best = (gain, trial)
        if best is None:
            return parts
        parts = best[1]
    return parts


def partition(ug: UnitGraph, cfg: ClusterConfig) -> tuple[Partition, float]:
    g = ug.affinity
    if g.number_of_nodes() == 0:
        return [], 0.0
    parts: Partition = [
        set(c) for c in louvain_communities(g, "weight", cfg.resolution, seed=cfg.seed)
    ]
    frozen: set[frozenset[int]] = set()
    parts = repair_cycles(ug, parts)
    for _ in range(6):
        before = sorted(map(sorted, parts))
        parts = repair_cycles(ug, split_oversized(ug, parts, cfg, frozen))
        if sorted(map(sorted, parts)) == before:
            break
    parts = refine(ug, parts, cfg)
    parts = merge_small(ug, parts, cfg)
    parts = merge_pass(ug, parts, cfg)
    parts = refine(ug, parts, cfg)
    if cfg.extract_constants and len(parts) > 1:
        parts = repair_cycles(ug, extract_constants(ug, parts, cfg.min_lines))
    parts = refine(ug, parts, cfg) if len(parts) > 1 else parts
    q = modularity(g, parts, weight="weight") if g.number_of_edges() else 0.0
    return parts, q
