"""Split a module into top-level *units* and compute their name-level dependencies."""

from __future__ import annotations

import ast
import contextlib
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class UnitKind(Enum):
    FUTURE = "future"  # from __future__ import ...
    IMPORT = "import"  # plain top-level import
    DEF = "def"  # function / class
    ASSIGN = "assign"  # binds names at module level
    STMT = "stmt"  # side-effect statement (binds nothing new)
    MAIN = "main"  # if __name__ == "__main__":
    DOCSTRING = "docstring"
    TYPING = "typing"  # if TYPE_CHECKING: <imports only>
    DUNDER = "dunder"  # __all__ / __version__ / ... -> package __init__
    DROPPED = "dropped"  # `del re`-style namespace cleanup


@dataclass
class Unit:
    idx: int
    kind: UnitKind
    node: ast.stmt
    start: int  # 1-based inclusive, including decorators and leading comments
    end: int  # 1-based inclusive
    source: str
    defines: set[str] = field(default_factory=set)
    uses: Counter[str] = field(default_factory=Counter)
    base_uses: set[str] = field(default_factory=set)  # base classes / decorators (strong ties)
    globals_written: set[str] = field(default_factory=set)  # `global x` rebinding
    rebinds: set[str] = field(default_factory=set)  # AugAssign / attribute / subscript targets
    ann_uses: set[str] = field(default_factory=set)  # names referenced *only* in annotations
    comment_tokens: list[str] = field(default_factory=list)  # words from the leading comment
    vocab: list[str] = field(default_factory=list)  # lexical tokens (identifiers, docs, comments)
    section: str = ""  # most recent banner comment ("# ---- storage ----") above this unit

    @property
    def runtime_uses(self) -> set[str]:
        return set(self.uses) - self.ann_uses

    @property
    def lines(self) -> int:
        return self.end - self.start + 1

    @property
    def label(self) -> str:
        if self.defines:
            return ", ".join(sorted(self.defines)[:3]) + ("…" if len(self.defines) > 3 else "")
        return f"<{self.kind.value}@{self.start}>"


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    t = node.test
    return (
        isinstance(t, ast.Compare)
        and isinstance(t.left, ast.Name)
        and t.left.id == "__name__"
        and len(t.comparators) == 1
        and isinstance(t.comparators[0], ast.Constant)
        and t.comparators[0].value == "__main__"
    )


def import_bindings(node: ast.Import | ast.ImportFrom) -> list[tuple[ast.alias, str]]:
    """Return (alias, bound_name) pairs; star imports bind '*'."""
    out = []
    for a in node.names:
        if a.name == "*":
            out.append((a, "*"))
        elif a.asname:
            out.append((a, a.asname))
        elif isinstance(node, ast.Import):
            out.append((a, a.name.split(".")[0]))
        else:
            out.append((a, a.name))
    return out


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_COMPS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _iter_scope(nodes: list[ast.AST]) -> list[ast.AST]:
    """All nodes belonging to the scope that `nodes` form, without entering nested scopes
    (a nested def/class/lambda/comprehension node itself is yielded, not its body)."""
    out: list[ast.AST] = []
    stack = list(reversed(nodes))
    while stack:
        n = stack.pop()
        out.append(n)
        if isinstance(n, _SCOPES + _COMPS):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(n))))
    return out


def _scope_bindings(body: list[ast.stmt]) -> tuple[set[str], set[str]]:
    """(local names, names declared global/nonlocal) for a function or class body."""
    local: set[str] = set()
    declared: set[str] = set()
    for n in _iter_scope(list(body)):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store | ast.Del):
            local.add(n.id)
        elif isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            local.add(n.name)
        elif isinstance(n, ast.TypeAlias):
            local.add(n.name.id)
        elif isinstance(n, ast.Import | ast.ImportFrom):
            local.update(b for _, b in import_bindings(n) if b != "*")
        elif isinstance(n, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and n.name:
            local.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            local.add(n.rest)
        elif isinstance(n, ast.Global | ast.Nonlocal):
            declared.update(n.names)
        elif isinstance(n, _COMPS):  # walrus inside a comprehension binds in this scope
            for w in ast.walk(n):
                if isinstance(w, ast.NamedExpr) and isinstance(w.target, ast.Name):
                    local.add(w.target.id)
    return local - declared, declared


def _arg_names(args: ast.arguments) -> set[str]:
    return {
        a.arg
        for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
        if a is not None
    }


class _Collector(ast.NodeVisitor):
    """Scope-aware walk of one top-level statement.

    * ``stores``: names bound at module scope
    * ``loads``: references that resolve to module scope (locals/closures filtered out)
    """

    def __init__(self) -> None:
        self.stores: set[str] = set()
        self.loads: Counter[str] = Counter()
        self.globals: set[str] = set()
        self.rebinds: set[str] = set()
        self.ann_loads: set[str] = set()
        self.runtime: set[str] = set()
        self.in_ann = 0
        # (is_class_scope, local names)
        self.scopes: list[tuple[bool, set[str]]] = []

    @property
    def depth(self) -> int:
        return len(self.scopes)

    def _is_module_ref(self, name: str) -> bool:
        for k, (is_class, local) in enumerate(reversed(self.scopes)):
            if is_class and k > 0:
                continue  # class bodies do not enclose nested functions
            if name in local:
                return False
        return True

    def _ref(self, name: str) -> None:
        if not self._is_module_ref(name):
            return
        if self.in_ann:
            self.ann_loads.add(name)
        else:
            self.runtime.add(name)
        self.loads[name] += 1

    # ---- scopes ------------------------------------------------------------
    def _push_type_params(self, node: ast.AST) -> bool:
        """PEP 695: `def f[T: Bound]` / `class C[T]` / `type A[T] = ...` open a scope."""
        params = getattr(node, "type_params", None)
        if not params:
            return False
        self.scopes.append((False, {tp.name for tp in params}))
        self.in_ann += 1
        for tp in params:
            for e in (getattr(tp, "bound", None), getattr(tp, "default_value", None)):
                if e is not None:
                    self.visit(e)
        self.in_ann -= 1
        return True

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for deco in node.decorator_list:
            self.visit(deco)
        for d in [*node.args.defaults, *node.args.kw_defaults]:
            if d is not None:
                self.visit(d)
        if self.depth == 0:
            self.stores.add(node.name)
        tp = self._push_type_params(node)
        self._annotations(node.args, node.returns)
        local, _ = _scope_bindings(node.body)
        self.scopes.append((False, local | _arg_names(node.args)))
        for st in node.body:
            self.visit(st)
        self.scopes.pop()
        if tp:
            self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for e in node.decorator_list:
            self.visit(e)
        if self.depth == 0:
            self.stores.add(node.name)
        tp = self._push_type_params(node)
        for base in [*node.bases, *node.keywords]:
            self.visit(base)
        # class bodies resolve names dynamically: `x = x` reads the *outer* x, so the local
        # set grows statement by statement
        local: set[str] = set()
        self.scopes.append((True, local))
        for st in node.body:
            self.visit(st)
            local |= _scope_bindings([st])[0]
        self.scopes.pop()
        if tp:
            self.scopes.pop()

    def visit_TypeAlias(self, node: ast.TypeAlias) -> None:
        if self.depth == 0:
            self.stores.add(node.name.id)
        tp = self._push_type_params(node)
        self.in_ann += 1  # lazily evaluated
        self.visit(node.value)
        self.in_ann -= 1
        if tp:
            self.scopes.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for d in [*node.args.defaults, *node.args.kw_defaults]:
            if d is not None:
                self.visit(d)
        self.scopes.append((False, _arg_names(node.args)))
        self.visit(node.body)
        self.scopes.pop()

    def _comp(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
        # the first iterable is evaluated in the enclosing scope
        self.visit(node.generators[0].iter)
        targets = {
            n.id for g in node.generators for n in ast.walk(g.target) if isinstance(n, ast.Name)
        }
        self.scopes.append((False, targets))
        for i, g in enumerate(node.generators):
            if i:
                self.visit(g.iter)
            for c in g.ifs:
                self.visit(c)
        for part in ("elt", "key", "value"):
            if (e := getattr(node, part, None)) is not None:
                self.visit(e)
        self.scopes.pop()

    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _comp

    # ---- annotations ---------------------------------------------------------
    def _annotations(self, args: ast.arguments, returns: ast.expr | None) -> None:
        for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
            if a is not None and a.annotation is not None:
                self._annotation(a.annotation)
        if returns is not None:
            self._annotation(returns)

    def _annotation(self, ann: ast.expr) -> None:
        self.in_ann += 1
        for n in ast.walk(ann):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                with contextlib.suppress(SyntaxError):
                    self.visit(ast.parse(n.value, mode="eval"))
        self.visit(ann)
        self.in_ann -= 1

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._annotation(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.target)

    # ---- bindings / references ---------------------------------------------------
    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        if self.depth == 0:
            self.stores.update(b for _, b in import_bindings(node) if b != "*")

    visit_ImportFrom = visit_Import

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            if self.depth == 0:
                self.rebinds.add(node.target.id)
            self._ref(node.target.id)
        else:
            self.visit(node.target)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._ref(node.id)
        elif self.depth == 0:
            if isinstance(node.ctx, ast.Del):
                self.rebinds.add(node.id)
            else:
                self.stores.add(node.id)

    def _store_target(self, node: ast.Attribute | ast.Subscript) -> None:
        if self.depth == 0 and isinstance(node.ctx, ast.Store | ast.Del):
            base = _base_name(node)
            if base:
                self.rebinds.add(base)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._store_target(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._store_target(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name and self.depth == 0:
            self.stores.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name and self.depth == 0:
            self.stores.add(node.name)
        self.generic_visit(node)


def _base_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


_COMMENT = re.compile(r"^\s*#")
_BANNER = re.compile(
    r"^#+\s*(?:[-=#*~]{3,}\s*)?([A-Za-z][\w /&,.-]*?)\s*[-=#*~]{3,}\s*$"
    r"|^#\s*[-=#*~]{3,}\s*$"
)


def _span(node: ast.stmt, lines: list[str], floor: int) -> tuple[int, int]:
    start = node.lineno
    decos = getattr(node, "decorator_list", None)
    if decos:
        start = min(start, *(d.lineno for d in decos))
    # absorb directly-attached comment block above
    while start - 1 > floor and _COMMENT.match(lines[start - 2]):
        start -= 1
    end = node.end_lineno or node.lineno
    return start, end


def _is_typing_block(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or node.orelse:
        return False
    t = node.test
    name = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else ""
    return name == "TYPE_CHECKING" and all(
        isinstance(s, ast.Import | ast.ImportFrom) for s in node.body
    )


_ENGLISH_STOP = frozenset(  # noqa: SIM905
    """the a an and or of to in on for with by is are be as at this that it its from not no
    if else when then than into out can will may should must do does done has have had was
    were been being which who whom what where how all any each other such only own same so
    too very just but also more most some none true false return returns self cls args
    kwargs arg kwarg param params""".split()  # noqa: SIM905
)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _norm_token(t: str) -> str | None:
    t = t.lower()
    if len(t) < 3 or t in _ENGLISH_STOP:
        return None
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and not t.endswith("ss") and len(t) > 3:
        return t[:-1]
    return t


def _split_ident(name: str) -> list[str]:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", parts)
    return [p for p in parts.split("_") if p]


def _vocabulary(node: ast.AST, src_lines: list[str]) -> list[str]:
    """Bag of lexical tokens: identifiers (split), attribute names, docstrings, comments."""
    raw: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            raw += _split_ident(n.id)
        elif isinstance(n, ast.Attribute):
            raw += _split_ident(n.attr)
        elif isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            raw += _split_ident(n.name) * 2  # own names count double
            doc = ast.get_docstring(n)
            if doc:
                raw += _WORD.findall(doc)
        elif isinstance(n, ast.arg | ast.keyword) and n.arg is not None:
            raw += _split_ident(n.arg)
    for ln in src_lines:
        i = ln.find("#")
        if i >= 0 and ln[:i].count('"') % 2 == 0 and ln[:i].count("'") % 2 == 0:
            raw += _WORD.findall(ln[i + 1 :])
    return [t for r in raw if (t := _norm_token(r))]


def has_lazy_annotations(units: list[Unit]) -> bool:
    return any(
        u.kind == UnitKind.FUTURE and any(a.name == "annotations" for a in u.node.names)  # type: ignore[attr-defined]
        for u in units
    )


def extract_units(source: str) -> tuple[list[Unit], str | None]:
    """Return units in source order and the module docstring (if any)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    units: list[Unit] = []
    docstring = ast.get_docstring(tree, clean=False)
    prev_end = 0
    section = ""
    for node in tree.body:
        for ln in lines[prev_end : node.lineno - 1]:
            m = _BANNER.match(ln)
            if m and m.group(1):
                section = m.group(1).strip().lower()
        start, end = _span(node, lines, prev_end)
        text = "\n".join(lines[start - 1 : end])
        if (
            not units
            and docstring is not None
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            kind = UnitKind.DOCSTRING
        elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
            kind = UnitKind.FUTURE
        elif isinstance(node, ast.Import | ast.ImportFrom):
            kind = UnitKind.IMPORT
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            kind = UnitKind.DEF
        elif _is_main_guard(node):
            kind = UnitKind.MAIN
        elif _is_typing_block(node):
            kind = UnitKind.TYPING
        else:
            kind = UnitKind.ASSIGN  # refined below
        u = Unit(len(units), kind, node, start, end, text)
        u.section = section
        u.vocab = _vocabulary(node, lines[start - 1 : end])
        u.comment_tokens = [
            w.lower()
            for ln in lines[start - 1 : node.lineno - 1]
            if _COMMENT.match(ln)
            for w in re.findall(r"[A-Za-z]{3,}", ln)
        ][:4]
        if kind not in (UnitKind.DOCSTRING, UnitKind.FUTURE, UnitKind.TYPING):
            c = _Collector()
            c.visit(node)
            u.defines = c.stores
            u.uses = c.loads
            u.globals_written = {
                n for x in ast.walk(node) if isinstance(x, ast.Global) for n in x.names
            }
            u.rebinds = c.rebinds - c.stores
            u.ann_uses = c.ann_loads - c.runtime
            if isinstance(node, ast.ClassDef):
                u.base_uses = {
                    n.id
                    for e in [*node.bases, *node.decorator_list]
                    for n in ast.walk(e)
                    if isinstance(n, ast.Name)
                }
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                u.base_uses = {
                    n.id
                    for e in node.decorator_list
                    for n in ast.walk(e)
                    if isinstance(n, ast.Name)
                }
            if kind == UnitKind.ASSIGN and not u.defines:
                u.kind = UnitKind.STMT
            if u.kind == UnitKind.ASSIGN and all(
                n.startswith("__") and n.endswith("__") for n in u.defines
            ):
                u.kind = UnitKind.DUNDER
            if kind == UnitKind.MAIN:
                u.defines = set()
        units.append(u)
        prev_end = end
    return units, docstring
