"""Build the unit dependency graph (with must-link groups) used for clustering."""

from __future__ import annotations

import ast
import builtins
import math
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import networkx as nx

from refactree.decompose.units import Unit, UnitKind, has_lazy_annotations, import_bindings

CODE_KINDS = (UnitKind.DEF, UnitKind.ASSIGN, UnitKind.STMT)

# tokens that carry no domain meaning when splitting identifiers
STOP_TOKENS = {
    "get", "set", "is", "has", "to", "from", "make", "create", "build", "do", "run", "the",
    "a", "an", "of", "on", "in", "for", "and", "or", "new", "init", "main", "default", "self",
    "cls", "helper", "util", "utils", "func", "data", "value", "values", "item", "items", "obj",
    "base", "impl", "handle", "process", "update", "load", "save", "add", "remove", "check",
    "with", "by", "all", "any", "one", "list", "dict", "str", "int", "type", "name", "_",
}  # fmt: skip


def split_identifier(name: str) -> list[str]:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower().split("_")
    return [p for p in parts if p and not p.isdigit()]


@dataclass
class Weights:
    """Relative strengths of the affinity signals."""

    reference: float = 1.0  # u uses a name defined by v
    inheritance: float = 3.0  # base class / decorator
    shared_import: float = 0.5  # both use the same external import (idf weighted)
    shared_token: float = 0.0  # (legacy) identifiers share a domain token (idf weighted)
    lexical: float = 1.0  # TF-IDF cosine similarity of vocabularies (kNN graph)
    lexical_k: int = 6  # neighbours per group in the lexical kNN graph
    lexical_min: float = 0.1  # ignore similarities below this
    locality: float = 0.15  # adjacent in the original file
    section: float = 0.4  # under the same banner comment in the original file
    shared_base: float = 1.0  # sibling classes deriving from the same local base
    annotation: float = 0.5  # multiplier for annotation-only references
    hub_fanout: int = 4  # references from groups touching more modules than this are damped


@dataclass
class UnitGraph:
    units: list[Unit]
    groups: list[list[int]]  # must-link groups of code-unit indices
    group_of: dict[int, int]  # unit idx -> group idx
    definer: dict[str, int]  # module-level name -> group idx
    external: dict[str, list[int]]  # bound import name -> import unit indices
    typing_external: set[str]  # names bound inside `if TYPE_CHECKING:` blocks
    deps: nx.DiGraph[int]  # group -> group (u needs v)
    affinity: nx.Graph[int]  # undirected weighted affinity between groups
    group_lines: dict[int, int] = field(default_factory=dict)
    group_ext: dict[int, set[str]] = field(default_factory=dict)
    lazy_annotations: bool = False
    deleted: set[str] = field(default_factory=set)  # `del`-ed at module level: not exported
    unresolved: set[str] = field(default_factory=set)  # injected dynamically (globals()[...])

    def group_label(self, g: int) -> str:
        return " + ".join(self.units[i].label for i in self.groups[g])

    def group_defines(self, g: int) -> set[str]:
        return set().union(*(self.units[i].defines for i in self.groups[g]))


class _UF:
    def __init__(self, items: list[int]) -> None:
        self.p = {i: i for i in items}

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def build_graph(
    units: list[Unit], weights: Weights | None = None, lazy_annotations: bool | None = None
) -> UnitGraph:
    w = weights or Weights()
    import_names = {
        b
        for u in units
        if u.kind == UnitKind.IMPORT
        for _, b in import_bindings(u.node)  # type: ignore[arg-type]
    }
    code_defined = {n for u in units if u.kind in CODE_KINDS for n in u.defines}
    for u in units:
        if (
            isinstance(u.node, ast.Delete)
            and u.rebinds
            and u.rebinds <= import_names - code_defined
        ):
            u.kind = UnitKind.DROPPED
    code = [u.idx for u in units if u.kind in CODE_KINDS]

    external: dict[str, list[int]] = defaultdict(list)
    typing_external: set[str] = set()
    for u in units:
        if u.kind == UnitKind.IMPORT:
            assert isinstance(u.node, ast.Import | ast.ImportFrom)
            for _, b in import_bindings(u.node):
                external[b].append(u.idx)
        elif u.kind == UnitKind.TYPING:
            assert isinstance(u.node, ast.If)
            for s in u.node.body:
                assert isinstance(s, ast.Import | ast.ImportFrom)
                for _, b in import_bindings(s):
                    typing_external.add(b)
                    external[b].append(u.idx)

    lazy = has_lazy_annotations(units) if lazy_annotations is None else lazy_annotations
    for u in units:
        if not lazy:
            u.ann_uses = set()
        elif isinstance(u.node, ast.ClassDef) and u.base_uses & external.keys():
            u.ann_uses = set()  # e.g. pydantic models resolve annotations at class creation

    # ---- must-link constraints -------------------------------------------------
    uf = _UF(code)
    unit_definers: dict[str, list[int]] = defaultdict(list)
    for i in code:
        for n in units[i].defines:
            unit_definers[n].append(i)
    for defs in unit_definers.values():  # redefinitions stay together
        for d in defs[1:]:
            uf.union(defs[0], d)

    def latest_definer(name: str, before: int) -> int | None:
        cands = [d for d in unit_definers.get(name, []) if d < before]
        return cands[-1] if cands else (unit_definers[name][0] if name in unit_definers else None)

    prev_code: int | None = None
    for i in code:
        u = units[i]
        # module-state mutation must live beside the state it mutates
        for n in u.rebinds | u.globals_written:
            owner = latest_definer(n, i)
            if owner is not None:
                uf.union(i, owner)
        if u.kind == UnitKind.STMT and not (u.rebinds & unit_definers.keys()):
            # pure side-effect statement: attach to most recent thing it touches, else predecessor
            touched = [t for n in u.uses if (t := latest_definer(n, i)) is not None and t < i]
            target = max(touched) if touched else prev_code
            if target is not None:
                uf.union(i, target)
        prev_code = i

    # names injected through globals()/vars() can only be resolved beside their injector
    module_dunders = {"__name__", "__file__", "__doc__", "__spec__", "__loader__",
                      "__package__", "__builtins__", "__path__", "__cached__"}  # fmt: skip
    known = unit_definers.keys() | external.keys() | set(dir(builtins)) | module_dunders
    unresolved = {n for i in code for n in units[i].uses} - known
    injectors = [
        i
        for i in code
        if any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in ("globals", "vars")
            for n in ast.walk(units[i].node)
        )
    ]
    if injectors and unresolved and "*" not in external:
        linked = injectors + [i for i in code if unresolved & units[i].uses.keys()]
        for i in linked[1:]:
            uf.union(linked[0], i)
    deleted = {n for i in code if isinstance(units[i].node, ast.Delete) for n in units[i].rebinds}

    roots: dict[int, int] = {}
    groups: list[list[int]] = []
    group_of: dict[int, int] = {}
    for i in code:
        r = uf.find(i)
        if r not in roots:
            roots[r] = len(groups)
            groups.append([])
        groups[roots[r]].append(i)
        group_of[i] = roots[r]

    definer = {n: group_of[ds[0]] for n, ds in unit_definers.items()}

    # ---- edges ---------------------------------------------------------------
    deps: nx.DiGraph[int] = nx.DiGraph()
    aff: nx.Graph[int] = nx.Graph()
    g_lines: dict[int, int] = {}
    g_ext: dict[int, set[str]] = {}
    g_tokens: dict[int, set[str]] = {}
    for g, members in enumerate(groups):
        g_lines[g] = sum(units[i].lines for i in members)
        deps.add_node(g)
        aff.add_node(g, lines=g_lines[g])
        g_ext[g] = {n for i in members for n in units[i].uses if n in external and n != "*"}
        g_tokens[g] = {
            t
            for i in members
            for n in units[i].defines
            for t in split_identifier(n)
            if t not in STOP_TOKENS and len(t) > 2
        }

    def bump(a: int, b: int, x: float) -> None:
        if a == b or x <= 0:
            return
        cur = aff.get_edge_data(a, b, {"weight": 0.0})["weight"]
        aff.add_edge(a, b, weight=cur + x)

    type_deps: nx.DiGraph[int] = nx.DiGraph()
    fan_in: dict[int, set[int]] = defaultdict(set)
    for g, members in enumerate(groups):
        for i in members:
            for n in units[i].uses:
                h = definer.get(n)
                if h is not None and h != g:
                    fan_in[h].add(g)
    for g, members in enumerate(groups):
        targets = {
            h
            for i in members
            for n in units[i].uses
            if (h := definer.get(n)) is not None and h != g
        }
        damp = min(1.0, math.sqrt(w.hub_fanout / len(targets))) if targets else 1.0
        for i in members:
            u = units[i]
            for n, cnt in u.uses.items():
                h = definer.get(n)
                if h is None or h == g:
                    continue
                if n in u.ann_uses:
                    type_deps.add_edge(g, h)
                    mult = w.annotation * w.reference
                else:
                    deps.add_edge(g, h)
                    mult = w.inheritance if n in u.base_uses else w.reference
                damp_in = min(1.0, math.sqrt(w.hub_fanout / len(fan_in[h])))
                bump(g, h, damp * damp_in * mult * (1.0 + math.log(cnt)))

    n_groups = max(len(groups), 1)

    def idf_pairs(feature: dict[int, set[str]], scale: float) -> None:
        index: dict[str, list[int]] = defaultdict(list)
        for g, feats in feature.items():
            for f in feats:
                index[f].append(g)
        for gs in index.values():
            df = len(gs)
            if df < 2 or df > max(2, n_groups // 2):
                continue  # ubiquitous features carry no signal
            s = scale * math.log(n_groups / df)
            for a_i in range(len(gs)):
                for b_i in range(a_i + 1, len(gs)):
                    bump(gs[a_i], gs[b_i], s)

    idf_pairs(g_ext, w.shared_import)
    idf_pairs(g_tokens, w.shared_token)
    idf_pairs(
        {
            g: {b for i in m if isinstance(units[i].node, ast.ClassDef) for b in units[i].base_uses}
            & definer.keys()
            for g, m in enumerate(groups)
        },
        w.shared_base,
    )
    idf_pairs(
        {g: {units[i].section for i in m if units[i].section} for g, m in enumerate(groups)},
        w.section,
    )

    _lexical_edges(units, groups, w, bump)

    order = sorted(range(len(groups)), key=lambda g: groups[g][0])
    for ga, gb in zip(order, order[1:], strict=False):
        bump(ga, gb, w.locality)

    # canonical insertion order: community detection is sensitive to it
    aff = _canonical(aff)
    deps = _canonical(deps)
    return UnitGraph(
        units, groups, group_of, definer, dict(external), typing_external,
        deps, aff, g_lines, g_ext, lazy, deleted, unresolved,
    )  # fmt: skip


def _lexical_edges(
    units: list[Unit], groups: list[list[int]], w: Weights, bump: Callable[[int, int, float], None]
) -> None:
    """Conceptual cohesion: groups talking about the same things belong together."""
    if w.lexical <= 0 or len(groups) < 3:
        return
    from sklearn.feature_extraction.text import TfidfVectorizer

    docs = [[t for i in g for t in units[i].vocab] for g in groups]
    if not any(docs):
        return
    vec = TfidfVectorizer(analyzer=lambda d: d, sublinear_tf=True, min_df=1, max_df=0.5)
    try:
        x = vec.fit_transform(docs)
    except ValueError:  # empty vocabulary after max_df pruning
        return
    sim = (x @ x.T).toarray()
    k = w.lexical_k
    for a in range(len(groups)):
        sim[a, a] = 0.0
        nbrs = sim[a].argsort()[::-1][:k]
        for b in nbrs:
            s = float(sim[a, b])
            if s < w.lexical_min:
                break
            if a < b or a not in sim[b].argsort()[::-1][:k]:  # add each mutual pair once
                bump(a, int(b), w.lexical * s)


def _canonical[G: (nx.Graph[int], nx.DiGraph[int])](g: G) -> G:
    out = g.__class__()
    for n in sorted(g.nodes):
        out.add_node(n, **g.nodes[n])
    for a, b in sorted(g.edges):
        attrs = dict(g.edges[a, b])
        if "weight" in attrs:  # float sums depend on accumulation order
            attrs["weight"] = round(attrs["weight"], 9)
        out.add_edge(a, b, **attrs)
    return out
