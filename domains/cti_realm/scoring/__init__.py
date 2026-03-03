"""CTI Realm scoring strategies for the SABER thin library.

Exports five :class:`SaberScoringStrategy` implementations and a factory
function that returns them keyed by strategy name.
"""

from pathlib import Path

from saber.scoring.strategies import SaberScoringStrategy

from .strategies import (
    CTIToolLLMStrategy,
    F1SigmaStrategy,
    ToolCallJaccardStrategy,
    TrajectoryAnalysisStrategy,
    TrajectoryJaccardStrategy,
)

__all__ = [
    "CTIToolLLMStrategy",
    "F1SigmaStrategy",
    "ToolCallJaccardStrategy",
    "TrajectoryAnalysisStrategy",
    "TrajectoryJaccardStrategy",
    "get_strategies",
]


def get_strategies(
    domain_root: Path,
) -> dict[str, SaberScoringStrategy]:
    """Create all CTI Realm scoring strategies.

    Auto-discovered by ``create_task`` when a ``scoring/`` package is
    present in the domain directory.

    Args:
        domain_root: Path to the domain root directory.

    Returns:
        Mapping of strategy name to strategy instance.
    """
    config_dir = domain_root / "tasks" / "cti_detection"
    return {
        "trajectory_analysis": TrajectoryAnalysisStrategy(config_dir),
        "cti_tool_llm": CTIToolLLMStrategy(config_dir),
        "trajectory_jaccard": TrajectoryJaccardStrategy(),
        "tool_call_jaccard": ToolCallJaccardStrategy(),
        "f1_sigma_scoring": F1SigmaStrategy(config_dir),
    }
