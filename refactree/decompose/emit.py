"""Render a DecompositionPlan into a package on disk."""

from __future__ import annotations

import ast
import copy
from pathlib import Path

from refactree.decompose.plan import DecompositionPlan
from refactree.decompose.units import Unit, UnitKind, import_bindings


def _render_import(u: Unit, used: set[str], node: ast.stmt | None = None) -> str | None:
    node = node or u.node
    assert isinstance(node, ast.Import | ast.ImportFrom)
    pairs = import_bindings(node)
    keep = [a for a, b in pairs if b == "*" or b in used]
    if not keep:
        return None
    relative = isinstance(node, ast.ImportFrom) and node.level > 0
    if len(keep) == len(pairs) and not relative and node is u.node:
        return u.source  # untouched: preserve formatting & comments
    new = copy.copy(node)
    new.names = keep
    if isinstance(new, ast.ImportFrom) and relative:
        new.level += 1  # we moved one package deeper
    return ast.unparse(new)


def _join_units(units: list[Unit], idxs: list[int]) -> str:
    chunks: list[str] = []
    prev: Unit | None = None
    for i in idxs:
        u = units[i]
        if prev is not None:
            if UnitKind.DEF in (u.kind, prev.kind):
                gap = 2
            elif prev.idx == u.idx - 1:
                gap = min(2, max(0, u.start - prev.end - 1))
            else:
                gap = 1
            chunks.append("\n" * gap)
        chunks.append(u.source + "\n")
        prev = u
    return "".join(chunks)


def _header(
    plan: DecompositionPlan,
    idxs: list[int],
    sibling_imports: dict[str, set[str]],
    dunder_imports: set[str],
    type_imports: dict[str, set[str]] | None = None,
    deferred: dict[str, set[str]] | None = None,
) -> str:
    units = plan.units
    type_imports = {k: v for k, v in (type_imports or {}).items() if v}
    deferred = {k: v for k, v in (deferred or {}).items() if v}
    used = {n for i in idxs for n in units[i].uses}
    typing_ext = used & plan.graph.typing_external
    need_tc = bool(type_imports or typing_ext or deferred)
    have_tc = "TYPE_CHECKING" in plan.graph.external
    if need_tc and have_tc:
        used.add("TYPE_CHECKING")
    out: list[str] = []
    futures = [u.source for u in units if u.kind == UnitKind.FUTURE]
    if futures:
        out += [*futures, ""]
    ext = [s for u in units if u.kind == UnitKind.IMPORT if (s := _render_import(u, used))]
    if need_tc and not have_tc:
        ext.append("from typing import TYPE_CHECKING")
    if ext:
        out += [*ext, ""]
    internal: list[str] = []
    if dunder_imports:
        internal.append(f"from . import {', '.join(sorted(dunder_imports))}")
    for mod, names in sorted(sibling_imports.items()):
        internal.append(_from_import(f".{mod}", names))
    if internal:
        out += [*internal, ""]
    if need_tc:
        block: list[str] = []
        for u in units:
            if u.kind == UnitKind.TYPING:
                assert isinstance(u.node, ast.If)
                for st in u.node.body:
                    if r := _render_import(u, typing_ext, st):
                        block.append(r)
        for mod, names in sorted(type_imports.items()):
            block.append(_from_import(f".{mod}", names))
        if deferred:
            block.append(
                "# Only used inside functions; bound at runtime by the package __init__ once\n"
                "# every module is loaded, which keeps the import graph acyclic."
            )
            for mod, names in sorted(deferred.items()):
                block.append(_from_import(f".{mod}", names))
        out.append("if TYPE_CHECKING:")
        out += ["    " + ln for b in block for ln in b.splitlines()]
        out.append("")
    return "\n".join(out) + ("\n" if out else "")


def _from_import(mod: str, names: set[str]) -> str:
    ns = sorted(names)
    one = f"from {mod} import {', '.join(ns)}"
    if len(one) <= 100:
        return one
    body = "".join(f"    {n},\n" for n in ns)
    return f"from {mod} import (\n{body})"


def _body(head: str, units: list[Unit], idxs: list[int]) -> str:
    """Header (which ends in a blank line) + code, with PEP 8 spacing at the seam."""
    code = _join_units(units, idxs)
    if not head:
        return code
    first = units[idxs[0]] if idxs else None
    sep = "\n" if first is not None and first.kind in (UnitKind.DEF, UnitKind.MAIN) else ""
    return head + sep + code


def render(plan: DecompositionPlan, package: str, export_private: bool = True) -> dict[str, str]:
    """Return {relative_path: source} for the generated package."""
    units = plan.units
    files: dict[str, str] = {}
    dunder_names = (
        set().union(*(units[i].defines for i in plan.dunder_units)) if plan.dunder_units else set()
    )

    for m in plan.modules:
        used = {n for i in m.units for n in units[i].uses}
        head = _header(
            plan,
            m.units,
            m.imports_from,
            used & dunder_names,
            m.type_imports_from,
            m.deferred_imports_from,
        )
        text = _body(head, units, m.units)
        files[f"{package}/{m.name}.py"] = text

    # __init__: docstring, dunders, re-exports of the original public surface
    sections: list[list[str]] = []
    if plan.docstring is not None:
        sections.append([units[0].source])
    sections.append([u.source for u in units if u.kind == UnitKind.FUTURE])
    sections.append([units[i].source for i in plan.dunder_units])
    exported: list[str] = []
    reexports: list[str] = []
    for m in plan.modules:
        pub = sorted(n for n in m.defines - plan.graph.deleted if not n.startswith("_"))
        if pub:
            reexports.append(_from_import(f".{m.name}", set(pub)))
            exported += pub
    sections.append(reexports)
    if export_private:
        private = [
            _from_import(f".{m.name}", priv) + "  # noqa: F401"
            for m in plan.modules
            if (priv := {n for n in m.defines - plan.graph.deleted if n.startswith("_")})
        ]
        # `import sys as _sys` style aliases are a common monkeypatching target
        private_ext = {n for n in plan.graph.external if n.startswith("_")}
        private += [
            r + "  # noqa: F401"
            for u in units
            if u.kind == UnitKind.IMPORT and (r := _render_import(u, private_ext))
        ]
        if private:
            sections.append(["# private names stay importable from the package", *private])
    wiring = [
        (m.name, src, n)
        for m in plan.modules
        for src, ns in sorted(m.deferred_imports_from.items())
        for n in sorted(ns)
    ]
    if wiring:
        mods = sorted({x for a, b, _ in wiring for x in (a, b)})
        lines = [
            "# Late binding of names that modules use only inside functions (see the",
            "# TYPE_CHECKING blocks there): all modules are fully loaded at this point.",
            "from sys import modules as _loaded",
            "",
            "_m = {",
            *(f"    {x!r}: _loaded[f'{{__name__}}.{x}']," for x in mods),
            "}",
        ]
        lines += [f"_m[{a!r}].{n} = _m[{b!r}].{n}" for a, b, n in wiring]
        lines.append("del _m, _loaded")
        sections.append(lines)
    if "__all__" not in dunder_names and exported:
        body = "".join(f"    {n!r},\n" for n in sorted(exported))
        sections.append([f"__all__ = [\n{body}]"])
    files[f"{package}/__init__.py"] = "\n\n".join("\n".join(x) for x in sections if x) + "\n"

    if plan.main_units:
        used = {n for i in plan.main_units for n in units[i].uses}
        runtime = {n for i in plan.main_units for n in units[i].runtime_uses}
        sib: dict[str, set[str]] = {}
        tsib: dict[str, set[str]] = {}
        for n in sorted(used):
            mod = plan.module_of(n)
            if mod:
                (sib if n in runtime else tsib).setdefault(mod, set()).add(n)
        head = _header(plan, plan.main_units, sib, used & dunder_names, tsib)
        files[f"{package}/__main__.py"] = _body(head, units, plan.main_units)
    return files


def write(files: dict[str, str], out_dir: Path) -> list[Path]:
    written = []
    for rel, text in files.items():
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        written.append(p)
    return written
