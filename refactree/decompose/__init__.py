"""Decompose a monolithic Python module into a cohesive, loosely-coupled package."""

from refactree.decompose.cluster import ClusterConfig
from refactree.decompose.emit import render, write
from refactree.decompose.graph import Weights
from refactree.decompose.plan import DecompositionPlan, ModulePlan, build_plan
from refactree.decompose.verify import VerifyReport, verify

__all__ = [
    "ClusterConfig",
    "DecompositionPlan",
    "ModulePlan",
    "VerifyReport",
    "Weights",
    "build_plan",
    "render",
    "verify",
    "write",
]
