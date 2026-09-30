# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for cti_realm/scoring/strategies.py — 5 checkpoint strategies."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cti_realm.scoring.strategies import (
    CTIAlignmentStrategy,
    DataExplorationStrategy,
    DetectionQualityStrategy,
    MITREJaccardStrategy,
    QueryIterationStrategy,
)
from saber.config.models import DomainCriteria

from .conftest import _make_ctx, _make_tool_step

# Valid Kusto response with actual rows
_KUSTO_OK = json.dumps({
    "Tables": [{
        "Columns": [{"ColumnName": "Result"}],
        "Rows": [["ok"]],
    }]
})


# =====================================================================
# C0: CTIAlignmentStrategy
# =====================================================================


class TestCTIAlignmentStrategy:

    @pytest.fixture()
    def strategy(self, tmp_path: Path) -> CTIAlignmentStrategy:
        (tmp_path / "cti_alignment_system.j2").write_text("Evaluate CTI research.")
        (tmp_path / "cti_alignment_user.j2").write_text("Objective: {{ question }}")
        return CTIAlignmentStrategy(prompts_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_no_cti_tools_returns_zero(self, strategy: CTIAlignmentStrategy) -> None:
        ctx = _make_ctx(submission="some text", max_score=1.25)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_cti_tools_calls_judge(self, strategy: CTIAlignmentStrategy) -> None:
        step = _make_tool_step(
            tool_name="get_cti_reports_by_tag",
            tool_input={"tag": "apt"},
            output='{"reports": [{"title": "APT Report"}]}',
        )
        criteria = DomainCriteria(detection_objective="Detect APT")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, max_score=1.25)

        mock_response = MagicMock()
        mock_response.completion = '{"score": 0.8, "reasoning": "good"}'
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._trajectory.get_model", return_value=mock_model):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.8 * 1.25)
        mock_model.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_scales_by_max_score(self, strategy: CTIAlignmentStrategy) -> None:
        step = _make_tool_step(tool_name="list_cti_report_tags")
        criteria = DomainCriteria(detection_objective="Detect X")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, max_score=2.5)

        mock_response = MagicMock()
        mock_response.completion = '{"score": 0.5}'
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._trajectory.get_model", return_value=mock_model):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.5 * 2.5)

    @pytest.mark.asyncio
    async def test_prompt_is_bounded_and_deduplicates_assistant_messages(self) -> None:
        prompts_dir = Path(__file__).resolve().parents[1] / "prompts" / "judge"
        strategy = CTIAlignmentStrategy(prompts_dir=prompts_dir)
        repeated_message = "FINAL_EXPLANATION " + ("relevant context " * 2000)
        steps = tuple(
            _make_tool_step(
                step_number=index,
                tool_name="get_cti_reports_by_tag" if index == 1 else "execute_kql_query",
                tool_input={"tag": "apt"} if index == 1 else {"query": "x"},
                output='{"title": "APT Report"}' if index == 1 else "",
                assistant_message=repeated_message,
                reasoning=repeated_message if index == 1 else f"reasoning-{index} " * 1000,
            )
            for index in range(1, 20)
        )
        criteria = DomainCriteria(detection_objective="Detect APT activity")
        ctx = _make_ctx(tool_steps=steps, criteria=criteria)
        mock_response = MagicMock(completion='{"score": 0.8}')
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._trajectory.get_model", return_value=mock_model):
            await strategy.score(ctx, None)

        messages = mock_model.generate.await_args.args[0]
        user_prompt = messages[1].content
        assert len(user_prompt) < 17_000
        assert user_prompt.count("FINAL_EXPLANATION") == 1
        assert "apt" in user_prompt
        assert "APT Report" in user_prompt

    @pytest.mark.asyncio
    async def test_non_json_score_uses_fallback(self, strategy: CTIAlignmentStrategy) -> None:
        step = _make_tool_step(tool_name="list_cti_report_tags")
        ctx = _make_ctx(tool_steps=(step,), criteria=DomainCriteria(detection_objective="Detect X"))
        mock_response = MagicMock(completion="The evidence is relevant. Score: 0.65")
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._trajectory.get_model", return_value=mock_model):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.65)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "completion",
        [
            "Your input exceeds the context window of this model. Please adjust your input and try again.",
            "The MAXIMUM CONTEXT LENGTH was exceeded for this request.",
        ],
    )
    async def test_context_window_response_raises(
        self, strategy: CTIAlignmentStrategy, completion: str
    ) -> None:
        step = _make_tool_step(tool_name="list_cti_report_tags")
        ctx = _make_ctx(tool_steps=(step,), criteria=DomainCriteria(detection_objective="Detect X"))
        mock_response = MagicMock(completion=completion)
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._trajectory.get_model", return_value=mock_model):
            with pytest.raises(RuntimeError, match="context window"):
                await strategy.score(ctx, None)


# =====================================================================
# C1: MITREJaccardStrategy
# =====================================================================


class TestMITREJaccardStrategy:

    @pytest.fixture()
    def strategy(self) -> MITREJaccardStrategy:
        return MITREJaccardStrategy()

    @pytest.mark.asyncio
    async def test_no_expected_returns_zero(self, strategy: MITREJaccardStrategy) -> None:
        ctx = _make_ctx(max_score=0.75)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_exact_match(self, strategy: MITREJaccardStrategy) -> None:
        criteria = DomainCriteria(expected_techniques=["T1059", "T1053"])
        step = _make_tool_step(output="Found T1059 and T1053")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, max_score=0.75)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_partial_match(self, strategy: MITREJaccardStrategy) -> None:
        criteria = DomainCriteria(expected_techniques=["T1059", "T1053"])
        step = _make_tool_step(output="Found T1059 only")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, max_score=0.75)
        result = await strategy.score(ctx, None)
        assert 0.0 < float(str(result.value)) < 0.75

    @pytest.mark.asyncio
    async def test_found_in_submission(self, strategy: MITREJaccardStrategy) -> None:
        criteria = DomainCriteria(expected_techniques=["T1059"])
        ctx = _make_ctx(submission="T1059 detected", criteria=criteria, max_score=0.75)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_found_in_reasoning(self, strategy: MITREJaccardStrategy) -> None:
        criteria = DomainCriteria(expected_techniques=["T1059"])
        step = _make_tool_step(reasoning="Analyzing T1059")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, max_score=0.75)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.75)


# =====================================================================
# C2: DataExplorationStrategy
# =====================================================================


class TestDataExplorationStrategy:

    @pytest.fixture()
    def strategy(self) -> DataExplorationStrategy:
        return DataExplorationStrategy()

    @pytest.mark.asyncio
    async def test_no_expected_returns_zero(self, strategy: DataExplorationStrategy) -> None:
        ctx = _make_ctx(max_score=1.0)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_all_tables_explored(self, strategy: DataExplorationStrategy) -> None:
        criteria = DomainCriteria(expected_data_sources=["DeviceProcessEvents", "SecurityEvent"])
        steps = (
            _make_tool_step(step_number=1, tool_name="get_table_schema", tool_input={"table_name": "DeviceProcessEvents"}),
            _make_tool_step(step_number=2, tool_name="sample_table_data", tool_input={"table_name": "SecurityEvent"}),
        )
        ctx = _make_ctx(tool_steps=steps, criteria=criteria, max_score=1.0)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_wrong_tool_not_counted(self, strategy: DataExplorationStrategy) -> None:
        criteria = DomainCriteria(expected_data_sources=["DeviceProcessEvents"])
        step = _make_tool_step(tool_name="execute_kql_query", tool_input={"table_name": "DeviceProcessEvents"})
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, max_score=1.0)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)


# =====================================================================
# C3: QueryIterationStrategy
# =====================================================================


class TestQueryIterationStrategy:

    @pytest.fixture()
    def strategy(self) -> QueryIterationStrategy:
        return QueryIterationStrategy()

    @pytest.mark.asyncio
    async def test_two_unique_queries_passes(self, strategy: QueryIterationStrategy) -> None:
        steps = (
            _make_tool_step(step_number=1, tool_name="execute_kql_query", tool_input={"query": "Q1"}, output=_KUSTO_OK),
            _make_tool_step(step_number=2, tool_name="execute_kql_query", tool_input={"query": "Q2"}, output=_KUSTO_OK),
        )
        ctx = _make_ctx(tool_steps=steps, max_score=0.5)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_single_query_fails(self, strategy: QueryIterationStrategy) -> None:
        step = _make_tool_step(tool_name="execute_kql_query", tool_input={"query": "Q1"}, output=_KUSTO_OK)
        ctx = _make_ctx(tool_steps=(step,), max_score=0.5)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_duplicate_queries_not_counted(self, strategy: QueryIterationStrategy) -> None:
        steps = (
            _make_tool_step(step_number=1, tool_name="execute_kql_query", tool_input={"query": "Q1"}, output=_KUSTO_OK),
            _make_tool_step(step_number=2, tool_name="execute_kql_query", tool_input={"query": "Q1"}, output=_KUSTO_OK),
        )
        ctx = _make_ctx(tool_steps=steps, max_score=0.5)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_no_queries_fails(self, strategy: QueryIterationStrategy) -> None:
        ctx = _make_ctx(max_score=0.5)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)


# =====================================================================
# C4: DetectionQualityStrategy
# =====================================================================


class TestDetectionQualityStrategy:

    @pytest.fixture()
    def strategy(self, tmp_path: Path) -> DetectionQualityStrategy:
        return DetectionQualityStrategy(prompts_dir=tmp_path)

    @pytest.fixture()
    def strategy_with_sigma(self, tmp_path: Path) -> DetectionQualityStrategy:
        (tmp_path / "sigma_quality_system.j2").write_text("You are a judge.")
        (tmp_path / "sigma_quality_user.j2").write_text("Rule: {{ pred_rule }}")
        return DetectionQualityStrategy(prompts_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_no_patterns_returns_zero(self, strategy: DetectionQualityStrategy) -> None:
        ctx = _make_ctx(submission="{}", max_score=6.5)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_f1_from_verified_results(self, strategy: DetectionQualityStrategy) -> None:
        criteria = DomainCriteria(regex_patterns={"FileName": r"cmd\.exe"})
        kusto_output = json.dumps({
            "stdout": json.dumps({
                "Tables": [{"Columns": [{"ColumnName": "FileName"}], "Rows": [["cmd.exe"]]}]
            })
        })
        step = _make_tool_step(tool_name="execute_kql_query", output=kusto_output)
        submission = json.dumps({"query_results": [{"FileName": "cmd.exe"}]})
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, submission=submission, max_score=6.5)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_sigma_with_llm_mock(self, strategy_with_sigma: DetectionQualityStrategy) -> None:
        criteria = DomainCriteria(detection_objective="Detect cred dumping", model="openai/gpt-4")
        submission = json.dumps({"sigma_rule": "title: Cred Dump\ndetection:\n  condition: sel"})
        ctx = _make_ctx(submission=submission, criteria=criteria, max_score=6.5)

        mock_response = MagicMock()
        mock_response.completion = '{"syntax_score": 0.8, "specificity": 0.9}'
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await strategy_with_sigma.score(ctx, None)

        # sigma = 0.25*0.8 + 0.75*0.9 = 0.875, raw = 0*5 + 0.875*1.5 = 1.3125
        assert float(str(result.value)) == pytest.approx(1.3125)

    @pytest.mark.asyncio
    async def test_value_capped_at_max_score(self, strategy_with_sigma: DetectionQualityStrategy) -> None:
        criteria = DomainCriteria(regex_patterns={"F": r"v"}, detection_objective="X", model="openai/gpt-4")
        kusto_output = json.dumps({
            "stdout": json.dumps({"Tables": [{"Columns": [{"ColumnName": "F"}], "Rows": [["v"]]}]})
        })
        step = _make_tool_step(tool_name="execute_kql_query", output=kusto_output)
        submission = json.dumps({"sigma_rule": "title: X\ndetection:\n  condition: sel"})
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, submission=submission, max_score=6.5)

        mock_response = MagicMock()
        mock_response.completion = '{"syntax_score": 1.0, "specificity": 1.0}'
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await strategy_with_sigma.score(ctx, None)

        assert float(str(result.value)) <= 6.5

    @pytest.mark.asyncio
    async def test_sigma_exception_propagates(self, strategy_with_sigma: DetectionQualityStrategy) -> None:
        criteria = DomainCriteria(detection_objective="Detect X")
        submission = json.dumps({"sigma_rule": "title: X\ndetection:\n  condition: sel"})
        ctx = _make_ctx(submission=submission, criteria=criteria, max_score=6.5)

        with patch("cti_realm.scoring.strategies.score_sigma_rule", side_effect=RuntimeError("LLM down")):
            with pytest.raises(RuntimeError, match="LLM down"):
                await strategy_with_sigma.score(ctx, None)
