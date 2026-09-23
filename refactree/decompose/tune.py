"""Fit signal weights and optimiser knobs to real package layouts (local, no network).

    uv run python -m refactree.decompose.tune [--rounds 3] [--out tuned.json]

Coordinate descent with multiplicative steps on mean ARI over a training split of the
benchmark corpus (ordered and shuffled variants averaged); a held-out split is reported
separately so gains that don't generalise are visible.
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import asdict, fields
from pathlib import Path

from refactree.decompose.bench import DEFAULT_CORPUS, run
from refactree.decompose.cluster import ClusterConfig
from refactree.decompose.graph import Weights

WEIGHT_KNOBS = [
    "reference", "inheritance", "shared_import", "lexical", "locality", "section",
    "shared_base", "annotation", "hub_fanout",
]  # fmt: skip
CONFIG_KNOBS = ["resolution", "interface_penalty"]


def split_corpus(corpus: list[str]) -> tuple[list[str], list[str]]:
    ordered = sorted(corpus)
    return ordered[0::2], ordered[1::2]


def evaluate(pkgs: list[str], w: Weights, cfg: ClusterConfig) -> float:
    total = 0.0
    for shuffle in (False, True):
        scores = run(pkgs, cfg, verbose=False, shuffle=shuffle, weights=w)
        total += sum(s.ari for s in scores) / max(1, len(scores))
    return total / 2


def _get(w: Weights, cfg: ClusterConfig, knob: str) -> float:
    return float(getattr(w, knob) if knob in WEIGHT_KNOBS else getattr(cfg, knob))


def _set(w: Weights, cfg: ClusterConfig, knob: str, value: float) -> tuple[Weights, ClusterConfig]:
    w, cfg = copy.copy(w), copy.copy(cfg)
    if knob == "hub_fanout":
        w.hub_fanout = max(1, round(value))
    elif knob in WEIGHT_KNOBS:
        setattr(w, knob, value)
    else:
        setattr(cfg, knob, value)
    return w, cfg


def tune(rounds: int = 3, log: bool = True) -> tuple[Weights, ClusterConfig, float, float]:
    train, hold = split_corpus(DEFAULT_CORPUS)
    w, cfg = Weights(), ClusterConfig()
    best = evaluate(train, w, cfg)
    base_hold = evaluate(hold, w, cfg)
    if log:
        print(f"start  train={best:.4f}  holdout={base_hold:.4f}", flush=True)
    step = 2.0
    for r in range(rounds):
        for knob in [*WEIGHT_KNOBS, *CONFIG_KNOBS]:
            cur = _get(w, cfg, knob)
            for factor in (step, 1 / step):
                val = cur * factor if cur else (0.25 if factor > 1 else 0.0)
                w2, c2 = _set(w, cfg, knob, val)
                score = evaluate(train, w2, c2)
                if score > best + 1e-4:
                    best, w, cfg = score, w2, c2
                    if log:
                        print(f"r{r} {knob:17} -> {val:<8.3g} train={best:.4f}", flush=True)
                    break
        step = step**0.5  # finer steps each round
    hold_score = evaluate(hold, w, cfg)
    if log:
        print(f"done   train={best:.4f}  holdout={hold_score:.4f} (was {base_hold:.4f})")
    return w, cfg, best, hold_score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("tuned.json"))
    a = ap.parse_args()
    w, cfg, train, hold = tune(a.rounds)
    cfg_d = {f.name: getattr(cfg, f.name) for f in fields(cfg) if f.name in CONFIG_KNOBS}
    a.out.write_text(
        json.dumps(
            {"weights": asdict(w), "config": cfg_d, "train": train, "holdout": hold}, indent=2
        )
    )
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
