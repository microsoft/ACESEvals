"""Tests for cti_realm/scoring/__init__.py — factory function."""

from __future__ import annotations

from pathlib import Path

from cti_realm.scoring import (
    CTIToolLLMStrategy,
    F1SigmaStrategy,
    ToolCallJaccardStrategy,
    TrajectoryAnalysisStrategy,
    TrajectoryJaccardStrategy,
    get_strategies,
)


class TestGetStrategies:
    """Tests for the get_strategies factory."""

    def test_returns_five_strategies(self, tmp_path: Path) -> None:
        strategies = get_strategies(tmp_path)
        assert len(strategies) == 5

    def test_strategy_names(self, tmp_path: Path) -> None:
        strategies = get_strategies(tmp_path)
        expected_keys = {
            "trajectory_analysis",
            "cti_tool_llm",
            "trajectory_jaccard",
            "tool_call_jaccard",
            "f1_sigma_scoring",
        }
        assert set(strategies.keys()) == expected_keys

    def test_strategy_types(self, tmp_path: Path) -> None:
        strategies = get_strategies(tmp_path)
        assert isinstance(strategies["trajectory_analysis"], TrajectoryAnalysisStrategy)
        assert isinstance(strategies["cti_tool_llm"], CTIToolLLMStrategy)
        assert isinstance(strategies["trajectory_jaccard"], TrajectoryJaccardStrategy)
        assert isinstance(strategies["tool_call_jaccard"], ToolCallJaccardStrategy)
        assert isinstance(strategies["f1_sigma_scoring"], F1SigmaStrategy)

    def test_all_strategies_have_score_method(self, tmp_path: Path) -> None:
        strategies = get_strategies(tmp_path)
        for name, strat in strategies.items():
            assert hasattr(strat, "score"), f"{name} missing score method"
            assert callable(strat.score), f"{name}.score not callable"

    def test_domain_root_passed_to_strategies(self, tmp_path: Path) -> None:
        """domain_root is accepted without error (files may not exist)."""
        strategies = get_strategies(tmp_path)
        # Should create strategies without error even with empty domain root
        assert len(strategies) == 5
