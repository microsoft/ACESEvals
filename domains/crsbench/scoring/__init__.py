"""CRSBench scoring strategies for SABER.

Exports the patch verification strategy and a factory function.
"""

from pathlib import Path

from saber.scoring.strategies import SaberScoringStrategy

from .patch_verify import CRSBenchPatchVerifyStrategy

__all__ = [
    "CRSBenchPatchVerifyStrategy",
    "get_strategies",
]


def get_strategies(
    domain_root: Path,  # noqa: ARG001
) -> dict[str, SaberScoringStrategy]:
    """Create all CRSBench scoring strategies.

    Auto-discovered by ``create_task`` when a ``scoring/`` package is
    present in the domain directory.

    Args:
        domain_root: Path to the domain root directory.

    Returns:
        Mapping of strategy name to strategy instance.
    """
    return {
        "crsbench_patch_verify": CRSBenchPatchVerifyStrategy(),
    }
