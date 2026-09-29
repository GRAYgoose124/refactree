"""Change-coupling from version control: code that changes together belongs together.

One local ``git blame --line-porcelain`` gives, for every line, the commit that last
touched it. Units whose lines were last touched by the same (small) commit were edited
together - a cheap, purely local proxy for the co-change coupling used in the software
architecture literature.
"""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path


def blame_commits(path: Path) -> list[str | None] | None:
    """Commit id per line (index 0 = line 1); None for uncommitted lines. None if no git."""
    try:
        res = subprocess.run(
            ["git", "blame", "--line-porcelain", "--", path.name],
            cwd=path.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    out: list[str | None] = []
    for ln in res.stdout.splitlines():
        if ln.startswith("\t"):
            continue
        head = ln.split(" ", 1)[0]
        if len(head) == 40 and all(c in "0123456789abcdef" for c in head):
            out.append(None if set(head) == {"0"} else head)
    return out


def remap(original: str, commits: list[str | None], rewritten: str) -> list[str | None]:
    """Carry per-line commits over to a rewritten source (e.g. after class splitting).

    Lines are matched by exact text; ambiguous (repeated) lines are left unmapped so they
    add no noise.
    """
    orig_lines = original.splitlines()
    counts = Counter(orig_lines)
    by_text: dict[str, deque[str | None]] = defaultdict(deque)
    for text, c in zip(orig_lines, commits, strict=False):
        if counts[text] == 1 and text.strip():
            by_text[text].append(c)
    return [by_text[t].popleft() if by_text.get(t) else None for t in rewritten.splitlines()]
