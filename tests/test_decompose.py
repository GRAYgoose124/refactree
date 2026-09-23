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
