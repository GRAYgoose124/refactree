"""Split oversized classes into mixins without changing behaviour.

``class Big(Base): <60 methods>`` becomes::

    class _BigParsingMixin:
        __slots__ = ()
        <parsing methods, verbatim>

    class Big(_BigParsingMixin, ..., Base):
        <everything that must stay>

MRO safety: ``Big.__mro__`` gains the mixins right after ``Big`` and before the original
bases, so attribute lookup on instances and subclasses resolves exactly as before, and a
moved method's zero-arg ``super()`` still continues into the original bases. Methods are
*pinned* to the core class when moving them could change meaning:

* dunders (``__init__``, ``__eq__``, ... class machinery and decorators like @dataclass
  inspect the class body itself)
* anything touching name-mangled ``__private`` attributes (mangling uses the class name)
* anything referencing ``__class__``
* any method whose name is looked up through ``super(...)`` inside the class (otherwise
  ``super().foo()`` from the core would now find the moved ``foo``)

Classes with PEP 695 type params, ``__slots__`` tricks, or special bases (Enum, NamedTuple,
TypedDict, Protocol) are left alone.
"""

from __future__ import annotations

import ast
import math
import re
from collections import Counter
from dataclasses import dataclass, field

import networkx as nx
from networkx.algorithms.community import louvain_communities

from refactree.decompose.units import _vocabulary

_SPECIAL_BASES = {
    "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "NamedTuple", "TypedDict", "Protocol",
    "BaseModel", "Structure", "Union",
}  # fmt: skip
_TOPIC_STOP = {
    "get", "set", "self", "the", "and", "for", "with", "from", "into", "value", "name", "item",
    "arg", "args", "make", "new", "check", "handle", "add", "remove", "update", "has", "can",
}  # fmt: skip


@dataclass
class ClassSplit:
    cls: str
    mixins: dict[str, list[str]] = field(default_factory=dict)  # mixin name -> methods
    pinned: list[str] = field(default_factory=list)


@dataclass
class _Method:
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    start: int  # 1-based, incl. decorators/comments
    end: int
    attrs: set[str]
    calls: set[str]
    vocab: list[str]
    pinned: str | None = None  # reason


def _self_name(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    decos = {ast.unparse(d) for d in fn.decorator_list}
    if "staticmethod" in decos:
        return None
    args = [*fn.args.posonlyargs, *fn.args.args]
    return args[0].arg if args else None


def _analyse(fn: ast.FunctionDef | ast.AsyncFunctionDef, method_names: set[str]) -> _Method:
    me = _self_name(fn)
    attrs: set[str] = set()
    calls: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == me:
            (calls if n.attr in method_names else attrs).add(n.attr)
    return _Method(fn.name, fn, fn.lineno, fn.end_lineno or fn.lineno, attrs, calls, [])


def _pin_reason(m: _Method, super_names: set[str]) -> str | None:
    fn = m.node
    if m.name.startswith("__") and m.name.endswith("__"):
        return "dunder"
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id == "__class__":
            return "__class__"
        name = n.attr if isinstance(n, ast.Attribute) else n.id if isinstance(n, ast.Name) else ""
        if name.startswith("__") and not name.endswith("__"):
            return "name-mangled"
    if m.name in super_names:
        return "reached via super()"
    if m.name.startswith("__"):
        return "name-mangled"
    return None


def _class_level_refs(cls: ast.ClassDef) -> set[str]:
    """Names read directly in the class body (`alias = method`, decorators, defaults)."""
    out: set[str] = set()
    for st in cls.body:
        if isinstance(st, ast.FunctionDef | ast.AsyncFunctionDef):
            exprs: list[ast.AST] = [*st.decorator_list, *st.args.defaults]
            exprs += [d for d in st.args.kw_defaults if d is not None]
        else:
            exprs = [st]
        for e in exprs:
            out |= {n.id for n in ast.walk(e) if isinstance(n, ast.Name)}
    return out


def _super_names(cls: ast.ClassDef) -> set[str]:
    out = set()
    for n in ast.walk(cls):
        if (
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
            and n.value.func.id == "super"
        ):
            out.add(n.attr)
    return out


def _topics(comms: list[list[_Method]], cls_tokens: set[str]) -> list[str]:
    """One distinctive CamelCase word per method community (TF-IDF across communities)."""
    bags: list[Counter[str]] = []
    for ms in comms:
        bag: Counter[str] = Counter()
        for m in ms:
            for t in re.split(r"_+", m.name.strip("_").lower()):
                if len(t) > 2:
                    bag[t] += 3
            bag.update(m.vocab)
        for t in list(bag):
            if t in _TOPIC_STOP or t in cls_tokens:
                del bag[t]
        bags.append(bag)
    df = Counter(t for b in bags for t in b)
    out: list[str] = []
    for k, bag in enumerate(bags):
        total = sum(bag.values()) or 1
        ranked = sorted(
            bag, key=lambda t: -(bag[t] / total) * (math.log((1 + len(bags)) / (1 + df[t])) + 1)
        )
        word = next((t.capitalize() for t in ranked if t.capitalize() not in out), f"Part{k + 1}")
        out.append(word)
    return out


def _eligible(cls: ast.ClassDef) -> bool:
    if getattr(cls, "type_params", None):
        return False
    base_names = {ast.unparse(b).split(".")[-1].split("[")[0] for b in cls.bases}
    if base_names & _SPECIAL_BASES:
        return False
    if any(k.arg == "metaclass" for k in cls.keywords):
        return False
    for st in cls.body:  # __slots__ must stay authoritative; don't interfere
        if isinstance(st, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__slots__" for t in st.targets
        ):
            return False
    return True


def plan_class_split(
    cls: ast.ClassDef, lines: list[str], max_lines: int, min_mixin_lines: int = 60
) -> tuple[ClassSplit, list[tuple[str, list[_Method]]], list[_Method]] | None:
    if not _eligible(cls):
        return None
    fns = [s for s in cls.body if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)]
    names = {f.name for f in fns}
    if len(names) != len(fns):
        return None  # overloads / property setters sharing a name: keep simple
    super_names = _super_names(cls)
    class_refs = _class_level_refs(cls)
    methods: list[_Method] = []
    for f in fns:
        m = _analyse(f, names)
        start = min([f.lineno, *(d.lineno for d in f.decorator_list)])
        while start - 1 > cls.lineno and lines[start - 2].strip().startswith("#"):
            start -= 1
        m.start = start
        m.vocab = _vocabulary(f, lines[start - 1 : m.end])
        m.pinned = _pin_reason(m, super_names)
        if m.pinned is None and m.name in class_refs:
            m.pinned = "referenced in class body"
        methods.append(m)
    movable = [m for m in methods if m.pinned is None]
    if sum(m.end - m.start + 1 for m in movable) < min_mixin_lines:
        return None

    # method affinity: shared instance state (IDF-weighted), calls, vocabulary
    g: nx.Graph[str] = nx.Graph()
    for m in methods:
        g.add_node(m.name)
    df = Counter(a for m in methods for a in m.attrs)
    n = max(1, len(methods))

    def bump(a: str, b: str, w: float) -> None:
        if a != b and w > 0:
            g.add_edge(a, b, weight=g.get_edge_data(a, b, {"weight": 0.0})["weight"] + w)

    for i, a in enumerate(methods):
        for b in methods[i + 1 :]:
            shared = a.attrs & b.attrs
            bump(a.name, b.name, sum(math.log(n / df[x]) for x in shared if df[x] < n))
        for c in a.calls:
            bump(a.name, c, 2.0)
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        docs = [m.vocab for m in methods]
        x = TfidfVectorizer(analyzer=lambda d: d, sublinear_tf=True, max_df=0.5).fit_transform(docs)
        sim = (x @ x.T).toarray()
        for i, a in enumerate(methods):
            for j in sim[i].argsort()[::-1][:5]:
                if j != i and sim[i, j] > 0.1:
                    bump(a.name, methods[j].name, float(sim[i, j]))
    except ValueError:
        pass

    by_name = {m.name: m for m in methods}
    sub = g.subgraph([m.name for m in movable])
    comms = sorted(
        (sorted(c) for c in louvain_communities(sub, "weight", 1.0, seed=0)),
        key=lambda c: min(by_name[x].start for x in c),
    )

    def size(comm: list[str]) -> int:
        return sum(by_name[x].end - by_name[x].start + 1 for x in comm)

    # merge small communities into their most connected sibling
    comms = [c for c in comms if c]
    changed = True
    while changed and len(comms) > 1:
        changed = False
        comms.sort(key=size)
        if size(comms[0]) < min_mixin_lines:
            small = comms.pop(0)
            best = max(
                comms,
                key=lambda c: sum(
                    g.get_edge_data(a, b, {"weight": 0.0})["weight"] for a in small for b in c
                ),
            )
            best.extend(small)
            changed = True
    comms = [c for c in comms if size(c) >= min_mixin_lines]
    if not comms:
        return None
    core_lines = (cls.end_lineno or cls.lineno) - cls.lineno + 1 - sum(size(c) for c in comms)
    if core_lines > 0.9 * ((cls.end_lineno or cls.lineno) - cls.lineno + 1):
        return None
    cls_tokens = {t.lower() for t in re.findall(r"[A-Z][a-z]+|[a-z]+", cls.name)}
    mixins: list[tuple[str, list[_Method]]] = []
    result = ClassSplit(cls.name, pinned=[f"{m.name} ({m.pinned})" for m in methods if m.pinned])
    ordered = [
        sorted((by_name[x] for x in comm), key=lambda m: m.start)
        for comm in sorted(comms, key=lambda cm: min(by_name[x].start for x in cm))
    ]
    for ms, topic in zip(ordered, _topics(ordered, cls_tokens), strict=True):
        mname = f"_{cls.name.lstrip('_')}{topic}Mixin"
        mixins.append((mname, ms))
        result.mixins[mname] = [m.name for m in ms]
    return result, mixins, methods


def split_classes(
    source: str, max_lines: int = 400, min_mixin_lines: int = 60
) -> tuple[str, list[ClassSplit]]:
    """Rewrite top-level classes longer than max_lines into core + mixins."""
    tree = ast.parse(source)
    lines = source.splitlines()
    edits: list[tuple[int, int, list[str]]] = []  # (start, end) 1-based inclusive -> new lines
    report: list[ClassSplit] = []
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        length = (cls.end_lineno or cls.lineno) - cls.lineno + 1
        if length <= max_lines:
            continue
        planned = plan_class_split(cls, lines, max_lines, min_mixin_lines)
        if planned is None:
            continue
        result, mixins, _ = planned
        moved = {m.name for _, ms in mixins for m in ms}
        cls_start = min([cls.lineno, *(d.lineno for d in cls.decorator_list)])
        out: list[str] = []
        for mname, ms in mixins:
            out.append(f"class {mname}:")
            out.append(f'    """{", ".join(m.name for m in ms[:4])}... of {cls.name}."""')
            out.append("")
            out.append("    __slots__ = ()")
            for m in ms:
                out.append("")
                out.extend(lines[m.start - 1 : m.end])
            out += ["", ""]
        # core class: original text minus moved spans, with mixins prepended to the bases
        header_end = cls.body[0].lineno - 1
        if isinstance(cls.body[0], ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            decos = cls.body[0].decorator_list
            header_end = min([cls.body[0].lineno, *(d.lineno for d in decos)]) - 1
        while header_end > cls.lineno and not lines[header_end - 1].rstrip().endswith(":"):
            header_end -= 1
        bases = [m for m, _ in mixins] + [ast.unparse(b) for b in cls.bases]
        bases += [ast.unparse(k) for k in cls.keywords]
        out.extend(lines[cls_start - 1 : cls.lineno - 1])  # decorators
        out.append(f"class {cls.name}({', '.join(bases)}):")
        skip: set[int] = set()
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and fn.name in moved:
                mm = next(m for _, ms in mixins for m in ms if m.name == fn.name)
                skip.update(range(mm.start, mm.end + 1))
        body = [
            ln
            for no, ln in enumerate(lines[header_end : cls.end_lineno], start=header_end + 1)
            if no not in skip
        ]
        # collapse the blank-line runs left behind by removed methods
        compact: list[str] = []
        for ln in body:
            if not ln.strip() and len(compact) >= 1 and not compact[-1].strip():
                continue
            compact.append(ln)
        while compact and not compact[-1].strip():
            compact.pop()
        out.extend(compact)
        edits.append((cls_start, cls.end_lineno or cls.lineno, out))
        report.append(result)
    for start, end, new in sorted(edits, reverse=True):
        lines[start - 1 : end] = new
    return "\n".join(lines) + ("\n" if source.endswith("\n") else ""), report
