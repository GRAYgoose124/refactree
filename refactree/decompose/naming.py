"""Name the modules of a partition the way a person would.

Priority: conventions (``cli``, ``constants``, ``errors``) > the author's own section
banners > an anchor class (the most central class that dominates the module) > the most
*distinctive* vocabulary (TF-IDF against sibling modules), pluralized for families.
"""

from __future__ import annotations

import ast
import keyword
import math
import re
import sys
from collections import Counter

import networkx as nx

from refactree.decompose.graph import STOP_TOKENS, UnitGraph, split_identifier
from refactree.decompose.units import UnitKind

_RESERVED = set(sys.stdlib_module_names) | {"__main__", "__init__", "test", "tests"}
_EXC_ROOTS = {"Exception", "BaseException", "Warning", "ValueError", "TypeError", "KeyError",
              "RuntimeError", "OSError", "LookupError", "AttributeError", "IOError",
              "IndexError", "NotImplementedError"}  # fmt: skip
_NOISE = STOP_TOKENS | {"mixin", "base", "abstract", "impl", "helper", "private", "internal"}


def _snake(name: str) -> str:
    toks = [t for t in split_identifier(name.lstrip("_")) if t != "mixin"]
    return "_".join(toks)


def _plural(word: str) -> str:
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es" if not word.endswith("s") else word
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _exception_classes(ug: UnitGraph) -> set[str]:
    bases: dict[str, set[str]] = {}
    for u in ug.units:
        if isinstance(u.node, ast.ClassDef):
            bases[u.node.name] = {ast.unparse(b).split(".")[-1] for b in u.node.bases}
    exc: set[str] = set()
    changed = True
    while changed:
        changed = False
        for c, bs in bases.items():
            if c not in exc and (bs & (_EXC_ROOTS | exc) or c.endswith(("Error", "Exception"))):
                exc.add(c)
                changed = True
    return exc


def name_modules(ug: UnitGraph, parts: list[set[int]], avoid: set[str]) -> dict[int, str]:
    units = ug.units
    exc = _exception_classes(ug)

    def lines(k: int) -> int:
        return sum(ug.group_lines[g] for g in parts[k])

    # distinctive vocabulary per module: identifiers defined there weigh most
    docs: list[Counter[str]] = []
    for p in parts:
        bag: Counter[str] = Counter()
        for g in p:
            for i in ug.groups[g]:
                for ident in units[i].defines:
                    for t in split_identifier(ident.lstrip("_")):
                        if len(t) > 2 and t not in _NOISE:
                            bag[t] += 4
                for t in units[i].vocab:
                    if t not in _NOISE:
                        bag[t] += 1
        docs.append(bag)
    df = Counter(t for d in docs for t in d)
    n = len(parts)

    def distinctive(k: int) -> list[tuple[float, str]]:
        d = docs[k]
        total = sum(d.values()) or 1
        return sorted(
            ((v / total) * (math.log((1 + n) / (1 + df[t])) + 1.0), t) for t, v in d.items()
        )[::-1]

    cands: dict[int, list[str]] = {}
    for k, p in enumerate(parts):
        mem = [units[i] for g in p for i in ug.groups[g]]
        defs = {n for u in mem for n in u.defines}
        classes = [u for u in mem if isinstance(u.node, ast.ClassDef)]
        c: list[str] = []
        if "main" in defs or any(u.kind == UnitKind.MAIN for u in mem):
            c.append("cli")
        if (
            n > 1
            and mem
            and all(
                u.kind == UnitKind.ASSIGN and all(x.lstrip("_").isupper() for x in u.defines)
                for u in mem
            )
        ):
            c.append("constants")
        cls_names = [u.node.name for u in classes]  # type: ignore[attr-defined]
        if cls_names and sum(1 for x in cls_names if x in exc) >= max(2, 0.7 * len(cls_names)):
            c += ["errors", "exceptions"]
        sec: Counter[str] = Counter()
        for u in mem:
            if u.section:
                sec[u.section] += u.lines
        if sec:
            s, v = sec.most_common(1)[0]
            if v >= 0.6 * lines(k) and len(split_identifier(s)) <= 3:
                c.append("_".join(split_identifier(s)))
        # anchor: most central class (intra-module references + subclassing) with real weight
        if classes:
            sub: nx.DiGraph[int] = ug.deps.subgraph(p).copy()
            pr = nx.pagerank(sub) if sub.number_of_edges() else dict.fromkeys(p, 1.0)
            best = max(
                classes,
                key=lambda u: (pr.get(ug.group_of[u.idx], 0.0) + 0.5) * u.lines,
            )
            if best.lines >= 0.35 * lines(k):
                c.append(_snake(best.node.name))  # type: ignore[attr-defined]
        dist = [t for _, t in distinctive(k)]
        if dist:
            top = dist[0]
            family = sum(1 for x in defs if top in split_identifier(x))
            c.append(_plural(top) if family >= 3 else top)
            if len(dist) > 1:
                c.append(f"{top}_{dist[1]}")
        c.append("core")
        cands[k] = c

    taken: set[str] = set()
    names: dict[int, str] = {}
    for k in sorted(range(n), key=lambda k: -lines(k)):  # big modules choose first
        for cand in cands[k]:
            cand = re.sub(r"\W", "_", cand).strip("_") or "core"
            if cand in _RESERVED or cand in avoid or keyword.iskeyword(cand):
                cand = f"{cand}_ops"
            if cand not in taken:
                break
        else:
            base, j = cands[k][0], 2
            while f"{base}{j}" in taken:
                j += 1
            cand = f"{base}{j}"
        names[k] = cand
        taken.add(cand)
    return names
