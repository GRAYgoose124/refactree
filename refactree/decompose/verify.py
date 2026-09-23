"""Check that a generated package is importable, lint-clean, and behaves like the original."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# F821 undefined name, F811 redefinition, F401 unused import, F404 late __future__, E9 syntax
_CHECKS = "F821,F811,F401,F404,E9"


def _ruff(path: Path) -> list[dict[str, Any]]:
    res = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--isolated", "--select", _CHECKS,
         "--output-format", "json", str(path)],
        capture_output=True, text=True,
    )  # fmt: skip
    try:
        out: list[dict[str, Any]] = json.loads(res.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ruff failed: {res.stderr.strip()}") from exc
    return out


def _symbol(message: str) -> str:
    m = re.search(r"`([^`]+)`", message)
    return m.group(1) if m else message


@dataclass
class VerifyReport:
    import_ok: bool = True
    import_error: str = ""
    missing_exports: list[str] = field(default_factory=list)
    lint_issues: list[str] = field(default_factory=list)
    run_match: bool | None = None
    run_diff: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.import_ok
            and not self.missing_exports
            and not self.lint_issues
            and self.run_match is not False
        )


def verify(
    out_dir: Path,
    package: str,
    expected_exports: set[str],
    original: Path | None = None,
    run_args: list[str] | None = None,
    check_import: bool = True,
) -> VerifyReport:
    r = VerifyReport()
    pkg_dir = out_dir / package
    # only report problems the split introduced: diff against the original's own findings
    baseline: Counter[tuple[str, str]] = Counter()
    if original is not None:
        for issue in _ruff(original):
            baseline[(issue["code"], _symbol(issue["message"]))] += 1
    for issue in _ruff(pkg_dir):
        fname = Path(issue["filename"]).name
        if issue["code"] == "F401" and fname == "__init__.py":
            continue  # re-exports
        key = (issue["code"], _symbol(issue["message"]))
        if baseline[key] > 0:
            baseline[key] -= 1
            continue
        r.lint_issues.append(
            f"{fname}:{issue['location']['row']} {issue['code']} {issue['message']}"
        )

    if check_import:
        probe = (
            f"import json, {package} as p; "
            f"print(json.dumps([n for n in {sorted(expected_exports)!r} if not hasattr(p, n)]))"
        )
        res = subprocess.run(
            [sys.executable, "-c", probe], cwd=out_dir, capture_output=True, text=True, timeout=120
        )
        if res.returncode != 0:
            r.import_ok = False
            r.import_error = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "?"
        else:
            r.missing_exports = json.loads(res.stdout.strip().splitlines()[-1])

    if original is not None and run_args is not None:
        # same argv[0] for both so usage/--help text that echoes the program name matches
        prog = original.stem
        here = original.resolve()
        run_orig = (
            f"import runpy, sys; sys.argv[0] = {prog!r}; sys.path.insert(0, {str(here.parent)!r}); "
            f"runpy.run_path({str(here)!r}, run_name='__main__')"
        )
        run_pkg = (
            f"import runpy, sys; sys.argv[0] = {prog!r}; "
            f"runpy.run_module({package + '.__main__'!r}, run_name='__main__')"
        )
        a = subprocess.run(
            [sys.executable, "-c", run_orig, *run_args],
            capture_output=True, text=True, timeout=300, cwd=out_dir,
        )  # fmt: skip
        b = subprocess.run(
            [sys.executable, "-c", run_pkg, *run_args],
            capture_output=True, text=True, timeout=300, cwd=out_dir,
        )  # fmt: skip
        r.run_match = (a.returncode, a.stdout) == (b.returncode, b.stdout)
        if not r.run_match:
            r.run_diff = (
                f"original rc={a.returncode}\n{a.stdout[-2000:]}{a.stderr[-1000:]}\n---\n"
                f"package rc={b.returncode}\n{b.stdout[-2000:]}{b.stderr[-1000:]}"
            )
    return r
