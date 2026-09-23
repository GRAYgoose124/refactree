"""Benchmark: flatten a real multi-module package into one monolith, decompose it, and
measure how well the original (authoritative) modularization is recovered.

    uv run python -m refactree.decompose.bench json email http logging ...
"""

from __future__ import annotations

import ast
import copy
import importlib
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from refactree.decompose.cluster import ClusterConfig
from refactree.decompose.graph import Weights
from refactree.decompose.plan import DecompositionPlan, build_plan
from refactree.decompose.units import UnitKind


@dataclass
class Monolith:
    name: str
    source: str
    truth: dict[str, str]  # top-level name in the monolith -> original module


def _package_dir(pkg: str) -> Path:
    mod = importlib.import_module(pkg)
    assert mod.__file__ is not None
    return Path(mod.__file__).parent


class _Rewrite(ast.NodeTransformer):
    """Rename top-level names and collapse `mod.attr` for internal module aliases."""

    def __init__(self, env: dict[str, str], mod_alias: dict[str, dict[str, str]]) -> None:
        self.env = env
        self.mod_alias = mod_alias

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.env:
            node.id = self.env[node.id]
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        if isinstance(node.value, ast.Name) and node.value.id in self.mod_alias:
            target = self.mod_alias[node.value.id].get(node.attr)
            if target is not None:
                return ast.copy_location(ast.Name(target, node.ctx), node)
        self.generic_visit(node)
        return node

    def _rename_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> ast.AST:
        if node.name in self.env:
            node.name = self.env[node.name]
        self.generic_visit(node)
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _rename_def  # noqa: N815


def _top_names(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for st in tree.body:
        if isinstance(st, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.add(st.name)
        elif isinstance(st, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            for t in targets:
                out |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
    return out


def flatten(pkg: str) -> Monolith:
    """Merge a flat package's modules into one module, keeping track of where names lived."""
    root = _package_dir(pkg)
    files = sorted(p for p in root.glob("*.py") if p.stem not in ("__init__", "__main__"))
    trees = {p.stem: ast.parse(p.read_text(encoding="utf-8")) for p in files}
    mods = set(trees)
    names = {m: _top_names(t) - {"__all__"} for m, t in trees.items()}
    counts: dict[str, int] = {}
    for ns in names.values():
        for n in ns:
            counts[n] = counts.get(n, 0) + 1
    glob = {m: {n: (n if counts[n] == 1 else f"{n}__{m}") for n in ns} for m, ns in names.items()}

    def internal(module: str | None, level: int) -> str | None:
        if level == 1 and module and module.split(".")[0] in mods:
            return module.split(".")[0]
        if level == 0 and module and module.startswith(pkg + "."):
            rest = module[len(pkg) + 1 :].split(".")[0]
            return rest if rest in mods else None
        return None

    ext_imports: list[str] = []
    seen_ext: set[str] = set()
    bodies: list[tuple[str, list[ast.stmt]]] = []
    truth: dict[str, str] = {}
    deps: nx.DiGraph[str] = nx.DiGraph()
    deps.add_nodes_from(sorted(mods))
    for m, tree in trees.items():
        env = dict(glob[m])
        mod_alias: dict[str, dict[str, str]] = {}
        body: list[ast.stmt] = []
        for st in tree.body:
            if isinstance(st, ast.ImportFrom):
                src = internal(st.module, st.level)
                if st.level == 1 and st.module is None:  # from . import a, b
                    for a in st.names:
                        if a.name in mods:
                            mod_alias[a.asname or a.name] = glob[a.name]
                            deps.add_edge(m, a.name)
                    continue
                if src is not None:
                    deps.add_edge(m, src)
                    for a in st.names:
                        if a.name in glob[src]:
                            env[a.asname or a.name] = glob[src][a.name]
                    continue
                if st.level > 0:
                    continue  # reaches outside the flattened package
            if isinstance(st, ast.Import):
                keep = []
                for a in st.names:
                    parts = a.name.split(".")
                    if parts[0] == pkg and len(parts) > 1 and parts[1] in mods and a.asname:
                        mod_alias[a.asname] = glob[parts[1]]
                        deps.add_edge(m, parts[1])
                    elif parts[0] != pkg:
                        keep.append(a)
                if not keep:
                    continue
                st.names = keep
            if isinstance(st, ast.Import | ast.ImportFrom):
                txt = ast.unparse(st)
                if st.col_offset == 0 and txt not in seen_ext:
                    seen_ext.add(txt)
                    ext_imports.append(txt)
                continue
            if isinstance(st, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in st.targets
            ):
                continue
            if isinstance(st, ast.If) and "__main__" in ast.unparse(st.test):
                continue
            if (
                isinstance(st, ast.Expr)
                and isinstance(st.value, ast.Constant)
                and isinstance(st.value.value, str)
            ):
                continue  # module docstring
            body.append(st)
        rw = _Rewrite(env, mod_alias)
        body = [rw.visit(st) for st in body]
        for n in glob[m].values():
            truth[n] = m
        bodies.append((m, body))

    order = {m: i for i, m in enumerate(_topo(deps))}
    bodies.sort(key=lambda mb: order[mb[0]])
    parts = ["\n".join(ext_imports)]
    for m, body in bodies:
        parts.append(f"# ---- {m} ----")  # stripped below unless banners are allowed
        parts.extend(ast.unparse(st) for st in body)
    return Monolith(pkg, "\n\n".join(parts) + "\n", truth)


def _topo(g: nx.DiGraph[str]) -> list[str]:
    cond = nx.condensation(g)
    order: list[str] = []
    for c in reversed(list(nx.topological_sort(cond))):
        order.extend(sorted(cond.nodes[c]["members"]))
    return order


@dataclass
class Score:
    name: str
    lines: int
    truth_modules: int
    modules: int
    ari: float
    nmi: float
    interface: int
    seconds: float


def score(
    mono: Monolith,
    cfg: ClusterConfig | None = None,
    banners: bool = False,
    shuffle: bool = False,
    weights: Weights | None = None,
) -> Score:
    src = mono.source
    if shuffle:  # destroy locality: only structure/semantics remain
        body = ast.parse(src).body
        head = [st for st in body if isinstance(st, ast.Import | ast.ImportFrom)]
        rest = [st for st in body if not isinstance(st, ast.Import | ast.ImportFrom)]
        random.Random(0).shuffle(rest)
        src = "\n\n".join(ast.unparse(st) for st in [*head, *rest]) + "\n"
    elif not banners:
        src = "\n".join(ln for ln in src.splitlines() if not ln.startswith("# ---- "))
    t0 = time.perf_counter()
    plan = build_plan(src, copy.deepcopy(cfg) if cfg else ClusterConfig(), weights)
    dt = time.perf_counter() - t0
    y_true, y_pred = _labels(plan, mono)
    return Score(
        mono.name,
        len(src.splitlines()),
        len(set(y_true)),
        len(plan.modules),
        adjusted_rand_score(y_true, y_pred),
        normalized_mutual_info_score(y_true, y_pred),
        plan.interface_width,
        dt,
    )


def _labels(plan: DecompositionPlan, mono: Monolith) -> tuple[list[str], list[str]]:
    """Per code unit (weighted by nothing): truth module vs predicted module."""
    y_true: list[str] = []
    y_pred: list[str] = []
    for m in plan.modules:
        for i in m.units:
            u = plan.units[i]
            if u.kind not in (UnitKind.DEF, UnitKind.ASSIGN):
                continue
            owners = [mono.truth[n] for n in u.defines if n in mono.truth]
            if owners:
                y_true.append(owners[0])
                y_pred.append(m.name)
    return y_true, y_pred


DEFAULT_CORPUS = [
    "json", "email", "http", "logging", "concurrent.futures", "importlib.metadata",
    "unittest", "xml.etree", "urllib", "wsgiref", "zoneinfo", "tomllib", "multiprocessing",
    "yaml", "git", "typer", "click", "nltk.tokenize", "networkx.algorithms.flow",
]  # fmt: skip


_CACHE: dict[str, Monolith] = {}


def run(
    pkgs: list[str],
    cfg: ClusterConfig | None = None,
    verbose: bool = True,
    shuffle: bool = False,
    weights: Weights | None = None,
) -> list[Score]:
    scores = []
    for p in pkgs:
        try:
            mono = _CACHE.get(p) or _CACHE.setdefault(p, flatten(p))
        except Exception as exc:  # noqa: BLE001
            print(f"{p:28} flatten failed: {exc}", file=sys.stderr)
            continue
        s = score(mono, cfg, shuffle=shuffle, weights=weights)
        scores.append(s)
        if verbose:
            print(
                f"{s.name:28} {s.lines:6}L  truth={s.truth_modules:3} got={s.modules:3}  "
                f"ARI={s.ari:.3f}  NMI={s.nmi:.3f}  iface={s.interface:4}  {s.seconds:.1f}s"
            )
    if scores and verbose:
        n = len(scores)
        print(
            f"{'MEAN':28} ARI={sum(s.ari for s in scores) / n:.3f}  "
            f"NMI={sum(s.nmi for s in scores) / n:.3f}"
        )
    return scores


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(args or DEFAULT_CORPUS, shuffle="--shuffle" in sys.argv)
