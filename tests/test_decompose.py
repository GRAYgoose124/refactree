"""Tests for monolith decomposition (refactree.decompose)."""

from __future__ import annotations

import shutil
import sysconfig
import textwrap
from pathlib import Path

import networkx as nx
import pytest

from refactree.decompose import ClusterConfig, build_plan, render, verify, write
from refactree.decompose.units import extract_units

FIXTURE = Path(__file__).parent / "fixtures" / "shop_monolith.py"


def _unit(src: str, name: str):
    units, _ = extract_units(textwrap.dedent(src))
    return next(u for u in units if name in u.defines)


# --- name resolution --------------------------------------------------------------------


def test_locals_and_params_do_not_leak_as_module_refs() -> None:
    u = _unit(
        """
        indent = 4
        def f(width):
            indent = width * 2
            return [indent for _ in range(width)]
        """,
        "f",
    )
    assert "indent" not in u.uses
    assert "width" not in u.uses


def test_comprehension_targets_are_local() -> None:
    u = _unit("p = 1\nq = [p for p in range(3)]\n", "q")
    assert "p" not in u.uses


def test_class_body_reads_outer_name_before_rebinding() -> None:
    u = _unit("_tpl = 'x'\nclass C:\n    _tpl = _tpl\n    y = _tpl\n", "C")
    assert u.uses["_tpl"] == 1  # only the first read escapes to module scope


def test_pep695_type_params_are_scoped_and_bounds_are_refs() -> None:
    u = _unit(
        """
        type _Func = int
        def override[F: _Func](method: F) -> F:
            return method
        """,
        "override",
    )
    assert "_Func" in u.uses
    assert "F" not in u.uses


def test_annotation_only_references_are_marked() -> None:
    u = _unit(
        """
        from __future__ import annotations
        class Order: ...
        def total(o: Order) -> int:
            return 1
        """,
        "total",
    )
    assert "Order" in u.ann_uses
    assert "Order" not in u.runtime_uses


# --- planning --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shop_plan():
    return build_plan(FIXTURE.read_text())


def _module_of(plan, name: str) -> str:
    mod = plan.module_of(name)
    assert mod is not None, name
    return mod


def test_cohesive_families_stay_together(shop_plan) -> None:
    same = [
        ("validate_sku", "validate_email", "ValidationError", "SKU_PATTERN"),
        ("format_money", "parse_money", "round_cents", "sum_money"),
        ("DiscountRule", "PercentOff", "BuyXGetY", "build_rule", "DISCOUNT_RULES"),
        ("Order", "OrderLine", "Product", "Customer"),
    ]
    homes = []
    for family in same:
        mods = {_module_of(shop_plan, n) for n in family}
        assert len(mods) == 1, (family, mods)
        homes.append(mods.pop())
    assert len(set(homes)) == len(homes), "distinct concerns should get distinct modules"


def test_module_state_is_colocated_with_its_mutators(shop_plan) -> None:
    assert _module_of(shop_plan, "_order_counter") == _module_of(shop_plan, "next_order_id")


def test_module_imports_are_acyclic(shop_plan) -> None:
    g = nx.DiGraph()
    for m in shop_plan.modules:
        g.add_node(m.name)
        for dep in m.imports_from:
            g.add_edge(m.name, dep)
    assert nx.is_directed_acyclic_graph(g)
    # modules are emitted in dependency order
    order = [m.name for m in shop_plan.modules]
    for a, b in g.edges:
        assert order.index(b) < order.index(a)


def test_interface_is_narrow(shop_plan) -> None:
    public = len(shop_plan.exports)
    assert 3 <= len(shop_plan.modules) <= 8
    assert shop_plan.interface_width < public


# --- end to end ------------------------------------------------------------------------


def test_generated_package_behaves_identically(tmp_path: Path, shop_plan) -> None:
    script = tmp_path / "shop.py"
    shutil.copy(FIXTURE, script)
    write(render(shop_plan, "shop"), tmp_path)
    for args in ([], ["--discount", "percent:pct=10"], ["--discount", "bxgy:sku=ABC-0001"]):
        report = verify(tmp_path, "shop", shop_plan.exports, original=script, run_args=args)
        assert report.ok, report
        assert report.run_match


STDLIB = Path(sysconfig.get_paths()["stdlib"])


@pytest.mark.parametrize(
    ("module", "run"),
    [("argparse", False), ("difflib", True), ("tarfile", True), ("configparser", False)],
)
def test_real_world_monoliths(tmp_path: Path, module: str, run: bool) -> None:
    src = STDLIB / f"{module}.py"
    if not src.exists():
        pytest.skip(f"{module}.py not available")
    script = tmp_path / f"{module}_orig.py"
    shutil.copy(src, script)
    plan = build_plan(script.read_text(), ClusterConfig())
    assert len(plan.modules) >= 3
    pkg = f"{module}_pkg"
    write(render(plan, pkg), tmp_path)
    report = verify(
        tmp_path,
        pkg,
        plan.exports,
        original=script,
        run_args=[] if run and plan.main_units else None,
    )
    assert report.ok, report


# --- class splitting ---------------------------------------------------------------------


def _big_class_source() -> str:
    parts = ["class Base:", "    def ping(self):", "        return 'base'", ""]
    parts += ["class Big(Base):", '    """A god class."""', "    kind = 'big'", ""]
    parts += ["    def __init__(self):", "        self.rows = []", "        self.cols = []"]
    parts += ["        self.__secret = 1", ""]
    for i in range(12):
        parts += [f"    def row_op{i}(self, x):", f"        self.rows.append(x + {i})"]
        parts += ["        return len(self.rows)", ""]
    for i in range(12):
        parts += [f"    def col_op{i}(self, x):", f"        self.cols.append(x * {i})"]
        parts += ["        return sum(self.cols)", ""]
    parts += ["    def peek(self):", "        return self.__secret", ""]
    parts += ["    def ping(self):", "        return 'big:' + super().ping()", ""]
    parts += ["    def pong(self):", "        return super().ping()", ""]
    parts += ["    alias = row_op0", ""]
    return "\n".join(parts) + "\n"


def test_class_split_preserves_behaviour_and_pins_unsafe_methods() -> None:
    from refactree.decompose.classsplit import split_classes

    src = _big_class_source()
    new, report = split_classes(src, max_lines=40, min_mixin_lines=20)
    assert len(report) == 1 and len(report[0].mixins) >= 2
    moved = {m for ms in report[0].mixins.values() for m in ms}
    assert "__init__" not in moved  # dunder
    assert "peek" not in moved  # name-mangled access
    assert "ping" not in moved  # reached via super()
    assert "row_op0" not in moved  # referenced in class body
    rows = {m for m in moved if m.startswith("row")}
    cols = {m for m in moved if m.startswith("col")}
    assert rows and cols
    assert not any(rows & set(ms) and cols & set(ms) for ms in report[0].mixins.values())

    old_ns: dict[str, object] = {}
    new_ns: dict[str, object] = {}
    exec(compile(src, "old", "exec"), old_ns)
    exec(compile(new, "new", "exec"), new_ns)
    for ns in (old_ns, new_ns):
        b = ns["Big"]()  # type: ignore[operator]
        ns["out"] = (b.row_op3(1), b.col_op2(5), b.peek(), b.ping(), b.pong(), b.alias(0))
    assert old_ns["out"] == new_ns["out"]


# --- naming ------------------------------------------------------------------------------


def test_exception_families_are_named_errors() -> None:
    src = "\n".join(
        [f"class E{i}Error(ValueError):\n    pass\n" for i in range(4)]
        + [f"def work{i}(x):\n    return x + {i}\n" for i in range(12)]
        + ["def boom():\n    raise E0Error(E1Error(E2Error(E3Error())))\n"]
    )
    plan = build_plan(src, ClusterConfig(min_lines=5))
    assert plan.module_of("E0Error") in ("errors", "exceptions")


# --- benchmark ---------------------------------------------------------------------------


def test_benchmark_recovers_json_package_structure() -> None:
    from refactree.decompose.bench import flatten, score

    s = score(flatten("json"))
    assert s.ari > 0.6, s
