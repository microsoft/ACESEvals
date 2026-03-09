"""Tests for cti_realm/scoring/strategies.py — 5 scoring strategies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cti_realm.scoring.strategies import (
    CTIToolLLMStrategy,
    F1SigmaStrategy,
    ToolCallJaccardStrategy,
    TrajectoryAnalysisStrategy,
    TrajectoryJaccardStrategy,
)
from saber.config.models import DomainCriteria

from .conftest import _make_ctx, _make_tool_step

if TYPE_CHECKING:
    from saber.scoring.templates import TemplateRenderer


# =====================================================================
# 1. TrajectoryAnalysisStrategy
# =====================================================================


class TestTrajectoryAnalysisStrategy:
    """Tests for the 5-checkpoint submission scorer."""

    @pytest.fixture()
    def strategy(self, tmp_path: Path) -> TrajectoryAnalysisStrategy:
        return TrajectoryAnalysisStrategy(prompts_dir=tmp_path)

    @pytest.fixture()
    def strategy_with_sigma(self, tmp_path: Path) -> TrajectoryAnalysisStrategy:
        (tmp_path / "sigma_quality_system.j2").write_text("You are a judge.")
        (tmp_path / "sigma_quality_user.j2").write_text(
            "Rule:\n{{ pred_rule }}\nContext: {{ context_type }}\n{{ evaluation_context }}"
        )
        return TrajectoryAnalysisStrategy(prompts_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_empty_submission(self, strategy: TrajectoryAnalysisStrategy) -> None:
        ctx = _make_ctx(submission="")
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_c0_cti_analysis(self, strategy: TrajectoryAnalysisStrategy) -> None:
        submission = json.dumps({"cti_analysis": "found APT group"})
        ctx = _make_ctx(submission=submission)
        result = await strategy.score(ctx, None)
        assert result.value is not None
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_c0_threat_intelligence_keyword(self, strategy: TrajectoryAnalysisStrategy) -> None:
        ctx = _make_ctx(submission="This threat_intelligence analysis reveals...")
        result = await strategy.score(ctx, None)
        # 'threat_intelligence' triggers C0 score
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_c1_expected_techniques(self, strategy: TrajectoryAnalysisStrategy) -> None:
        criteria = DomainCriteria(
            expected_techniques=["T1059", "T1053"],
        )
        submission = "The attacker used T1059 for code execution."
        ctx = _make_ctx(submission=submission, criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_c2_expected_data_sources(self, strategy: TrajectoryAnalysisStrategy) -> None:
        criteria = DomainCriteria(
            expected_data_sources=["DeviceProcessEvents", "SecurityEvent"],
        )
        submission = "Query used DeviceProcessEvents and SecurityEvent tables."
        ctx = _make_ctx(submission=submission, criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_c3_kql_keywords(self, strategy: TrajectoryAnalysisStrategy) -> None:
        submission = json.dumps({"kql_query": "DeviceProcessEvents | where FileName == 'cmd.exe'"})
        ctx = _make_ctx(submission=submission)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_c4_regex_patterns_f1(self, strategy: TrajectoryAnalysisStrategy) -> None:
        criteria = DomainCriteria(
            regex_patterns={"FileName": r"cmd\.exe"},
        )
        submission = json.dumps({
            "kql_query": "DeviceProcessEvents | where FileName == 'cmd.exe'",
            "query_results": [{"FileName": "cmd.exe"}],
        })
        ctx = _make_ctx(submission=submission, criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_max_score_scaling(self, strategy: TrajectoryAnalysisStrategy) -> None:
        submission = json.dumps({"cti_analysis": "data"})
        ctx = _make_ctx(submission=submission, max_score=10.0)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) <= 10.0

    @pytest.mark.asyncio
    async def test_explanation_contains_checkpoints(self, strategy: TrajectoryAnalysisStrategy) -> None:
        submission = json.dumps({"cti_analysis": "x"})
        ctx = _make_ctx(submission=submission)
        result = await strategy.score(ctx, None)
        assert result.explanation is not None
        assert "C0=" in result.explanation
        assert "C4=" in result.explanation

    @pytest.mark.asyncio
    async def test_sigma_exception_propagates(
        self, strategy_with_sigma: TrajectoryAnalysisStrategy
    ) -> None:
        """When LLM judge fails, exception propagates to caller."""
        criteria = DomainCriteria(
            regex_patterns={},
            detection_objective="Detect lateral movement",
        )
        submission = json.dumps({
            "sigma_rule": "title: Lateral Movement\ndetection:\n  condition: selection",
        })
        ctx = _make_ctx(submission=submission, criteria=criteria)

        with patch("cti_realm.scoring.strategies.score_sigma_rule", side_effect=RuntimeError("LLM down")):
            with pytest.raises(RuntimeError, match="LLM down"):
                await strategy_with_sigma.score(ctx, None)

    @pytest.mark.asyncio
    async def test_c0_exact_score_value(self, strategy: TrajectoryAnalysisStrategy) -> None:
        """C0 alone (from cti_analysis key) should give exactly 1.25/10 * max_score."""
        submission = json.dumps({"cti_analysis": "found APT"})
        ctx = _make_ctx(submission=submission, max_score=1.0)
        result = await strategy.score(ctx, None)
        # C0=1.25, total=1.25/10=0.125
        assert float(str(result.value)) == pytest.approx(0.125)

    @pytest.mark.asyncio
    async def test_c1_proportional_scoring(self, strategy: TrajectoryAnalysisStrategy) -> None:
        """Finding 1 of 3 techniques gives exactly (1/3)*0.75/10 * max_score."""
        criteria = DomainCriteria(expected_techniques=["T1059", "T1053", "T1027"])
        submission = "Analysis shows T1059 in use."
        ctx = _make_ctx(submission=submission, criteria=criteria, max_score=1.0)
        result = await strategy.score(ctx, None)
        expected_c1 = (1.0 / 3.0) * 0.75
        expected_normalized = expected_c1 / 10.0
        assert float(str(result.value)) == pytest.approx(expected_normalized)


# =====================================================================
# 2. CTIToolLLMStrategy
# =====================================================================


class TestCTIToolLLMStrategy:
    """Tests for CTI tool detection + LLM quality (thin wrapper over LLMJudgeStrategy)."""

    @pytest.fixture()
    def strategy(self) -> CTIToolLLMStrategy:
        return CTIToolLLMStrategy()

    @pytest.fixture()
    def cti_criteria(self) -> DomainCriteria:
        """DomainCriteria with complete LLM judge config extras."""
        return DomainCriteria(
            model="openai/gpt-4",
            judge_system_template="judge/cti_alignment_system.j2",
            judge_user_template="judge/cti_alignment_user.j2",
            response_format="continuous",
        )

    @pytest.fixture()
    def renderer(self) -> "TemplateRenderer":
        from saber.scoring.templates import TemplateRenderer

        return TemplateRenderer(
            templates={
                "judge/cti_alignment_system.j2": "You are a CTI evaluator.",
                "judge/cti_alignment_user.j2": "Evaluate: {{ question }}",
            }
        )

    @pytest.mark.asyncio
    async def test_no_cti_tools_returns_zero(self, strategy: CTIToolLLMStrategy) -> None:
        step = _make_tool_step(tool_name="execute_kql_query", output="result")
        ctx = _make_ctx(tool_steps=(step,))
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)
        assert result.explanation is not None
        assert "No CTI tools" in result.explanation

    @pytest.mark.asyncio
    async def test_cti_tools_but_no_config(self, strategy: CTIToolLLMStrategy) -> None:
        """DomainCriteria with no model/template extras -> 0."""
        step = _make_tool_step(tool_name="get_cti_reports_by_tag", tool_input={"tag": "apt"})
        ctx = _make_ctx(tool_steps=(step,))
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)
        assert result.explanation is not None
        assert "Missing" in result.explanation

    @pytest.mark.asyncio
    async def test_requires_template_renderer(
        self,
        strategy: CTIToolLLMStrategy,
        cti_criteria: DomainCriteria,
    ) -> None:
        """If renderer is not a TemplateRenderer, returns 0."""
        step = _make_tool_step(tool_name="get_cti_reports_by_tag", tool_input={"tag": "apt"})
        ctx = _make_ctx(tool_steps=(step,), criteria=cti_criteria)
        result = await strategy.score(ctx, "not_a_renderer")
        assert result.value == pytest.approx(0.0)
        assert result.explanation is not None
        assert "TemplateRenderer" in result.explanation

    @pytest.mark.asyncio
    async def test_delegates_to_llm_judge_strategy(
        self,
        strategy: CTIToolLLMStrategy,
        cti_criteria: DomainCriteria,
        renderer: "TemplateRenderer",
    ) -> None:
        """Verifies delegation to LLMJudgeStrategy with correct criteria."""
        from inspect_ai.scorer import Score as InspectScore

        step = _make_tool_step(
            tool_name="get_cti_reports_by_tag",
            tool_input={"tag": "lateral_movement"},
            reasoning="Searching for lateral movement CTI reports.",
        )
        ctx = _make_ctx(
            tool_steps=(step,),
            criteria=cti_criteria,
            metadata={"description": "Detect lateral movement"},
        )

        expected_score = InspectScore(value=0.85, answer="", explanation="Good CTI usage")
        mock_judge = AsyncMock(return_value=expected_score)

        with patch("saber.scoring.strategies.LLMJudgeStrategy") as MockClass:
            MockClass.return_value.score = mock_judge
            result = await strategy.score(ctx, renderer)

        # LLMJudgeStrategy().score() was called once
        mock_judge.assert_called_once()
        call_ctx = mock_judge.call_args[0][0]

        # The delegated context should have LLMJudgeCriteria
        from saber.config.models import LLMJudgeCriteria

        assert isinstance(call_ctx.scorer.criteria, LLMJudgeCriteria)
        assert call_ctx.scorer.criteria.model == "openai/gpt-4"
        assert call_ctx.scorer.criteria.system_template == "judge/cti_alignment_system.j2"
        assert call_ctx.scorer.criteria.user_template == "judge/cti_alignment_user.j2"
        assert result.value == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(
        self,
        strategy: CTIToolLLMStrategy,
        cti_criteria: DomainCriteria,
        renderer: "TemplateRenderer",
    ) -> None:
        step = _make_tool_step(tool_name="list_cti_report_tags")
        ctx = _make_ctx(tool_steps=(step,), criteria=cti_criteria)

        with patch("saber.scoring.strategies.LLMJudgeStrategy") as MockClass:
            MockClass.return_value.score = AsyncMock(side_effect=RuntimeError("API down"))
            with pytest.raises(RuntimeError, match="API down"):
                await strategy.score(ctx, renderer)

    @pytest.mark.asyncio
    async def test_multiple_cti_tools_delegated(
        self,
        strategy: CTIToolLLMStrategy,
        cti_criteria: DomainCriteria,
        renderer: "TemplateRenderer",
    ) -> None:
        """Multiple CTI tool steps still pass gate and delegate correctly."""
        from inspect_ai.scorer import Score as InspectScore

        steps = (
            _make_tool_step(step_number=1, tool_name="get_cti_reports_by_tag", tool_input={"tag": "apt"}),
            _make_tool_step(step_number=2, tool_name="get_cti_reports_by_tag", tool_input={"tag": "persistence"}),
        )
        ctx = _make_ctx(tool_steps=steps, criteria=cti_criteria)

        expected_score = InspectScore(value=0.6, answer="", explanation="ok")
        with patch("saber.scoring.strategies.LLMJudgeStrategy") as MockClass:
            MockClass.return_value.score = AsyncMock(return_value=expected_score)
            result = await strategy.score(ctx, renderer)

        assert result.value == pytest.approx(0.6)


# =====================================================================
# 3. TrajectoryJaccardStrategy
# =====================================================================


class TestTrajectoryJaccardStrategy:
    """Tests for regex + Jaccard similarity over trajectory."""

    @pytest.fixture()
    def strategy(self) -> TrajectoryJaccardStrategy:
        return TrajectoryJaccardStrategy()

    @pytest.mark.asyncio
    async def test_no_expected_items(self, strategy: TrajectoryJaccardStrategy) -> None:
        ctx = _make_ctx()
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)
        assert result.explanation is not None
        assert "No expected_items" in result.explanation

    @pytest.mark.asyncio
    async def test_exact_match_all_items(self, strategy: TrajectoryJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_items=["T1059", "T1053"],
            regex_pattern=r"T\d{4}(?:\.\d{3})?",
        )
        step = _make_tool_step(
            output="Found techniques T1059 and T1053 in the data.",
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_match(self, strategy: TrajectoryJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_items=["T1059", "T1053", "T1027"],
            regex_pattern=r"T\d{4}(?:\.\d{3})?",
        )
        step = _make_tool_step(output="T1059 found")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        val = float(str(result.value))
        assert 0.0 < val < 1.0

    @pytest.mark.asyncio
    async def test_extra_items_reduce_jaccard(self, strategy: TrajectoryJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_items=["T1059"],
            regex_pattern=r"T\d{4}(?:\.\d{3})?",
        )
        step = _make_tool_step(output="T1059 T1053 T1027 T1566")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        val = float(str(result.value))
        # Jaccard = 1/4 = 0.25
        assert val == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_items_found_in_tool_input(self, strategy: TrajectoryJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_items=["T1059"],
            regex_pattern=r"T\d{4}(?:\.\d{3})?",
        )
        step = _make_tool_step(
            tool_input={"query": "T1059"},
            output="no match in output",
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_items_found_in_assistant_message(self, strategy: TrajectoryJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_items=["T1059"],
            regex_pattern=r"T\d{4}(?:\.\d{3})?",
        )
        step = _make_tool_step(assistant_message="I'll look for T1059")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_default_regex_pattern(self, strategy: TrajectoryJaccardStrategy) -> None:
        """If no regex_pattern in criteria, default T\\d{4} is used."""
        criteria = DomainCriteria(
            expected_items=["T1059"],
        )
        step = _make_tool_step(output="T1059 detected")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_max_score_scaling(self, strategy: TrajectoryJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_items=["T1059"],
            regex_pattern=r"T\d{4}",
        )
        step = _make_tool_step(output="T1059")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, max_score=5.0)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_items_found_in_reasoning(self, strategy: TrajectoryJaccardStrategy) -> None:
        """Items should be found via the reasoning field on ToolStep."""
        criteria = DomainCriteria(
            expected_items=["T1059"],
            regex_pattern=r"T\d{4}(?:\.\d{3})?",
        )
        step = _make_tool_step(reasoning="Analyzing T1059 technique")
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0


# =====================================================================
# 4. ToolCallJaccardStrategy
# =====================================================================


class TestToolCallJaccardStrategy:
    """Tests for tool call param extraction + Jaccard."""

    @pytest.fixture()
    def strategy(self) -> ToolCallJaccardStrategy:
        return ToolCallJaccardStrategy()

    @pytest.mark.asyncio
    async def test_missing_config(self, strategy: ToolCallJaccardStrategy) -> None:
        ctx = _make_ctx()
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_all_tables_matched(self, strategy: ToolCallJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_tools=["get_table_schema"],
            expected_items=["DeviceProcessEvents", "SecurityEvent"],
            param_name="table_name",
        )
        steps = (
            _make_tool_step(
                step_number=1,
                tool_name="get_table_schema",
                tool_input={"table_name": "DeviceProcessEvents"},
            ),
            _make_tool_step(
                step_number=2,
                tool_name="get_table_schema",
                tool_input={"table_name": "SecurityEvent"},
            ),
        )
        ctx = _make_ctx(tool_steps=steps, criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_tool_match(self, strategy: ToolCallJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_tools=["get_table_schema"],
            expected_items=["DeviceProcessEvents", "SecurityEvent", "Syslog"],
            param_name="table_name",
        )
        step = _make_tool_step(
            tool_name="get_table_schema",
            tool_input={"table_name": "DeviceProcessEvents"},
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        val = float(str(result.value))
        assert 0.0 < val < 1.0

    @pytest.mark.asyncio
    async def test_wrong_tool_ignored(self, strategy: ToolCallJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_tools=["get_table_schema"],
            expected_items=["DeviceProcessEvents"],
            param_name="table_name",
        )
        step = _make_tool_step(
            tool_name="execute_kql_query",
            tool_input={"table_name": "DeviceProcessEvents"},
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_string_expected_tools_coerced(self, strategy: ToolCallJaccardStrategy) -> None:
        """expected_tools as a string should be coerced to list."""
        criteria = DomainCriteria(
            expected_tools="get_table_schema",
            expected_items=["Syslog"],
            param_name="table_name",
        )
        step = _make_tool_step(
            tool_name="get_table_schema",
            tool_input={"table_name": "Syslog"},
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_default_param_name_is_table(self, strategy: ToolCallJaccardStrategy) -> None:
        criteria = DomainCriteria(
            expected_tools=["get_table_schema"],
            expected_items=["Syslog"],
        )
        step = _make_tool_step(
            tool_name="get_table_schema",
            tool_input={"table": "Syslog"},
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria)
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) == pytest.approx(1.0)


# =====================================================================
# 5. F1SigmaStrategy
# =====================================================================


class TestF1SigmaStrategy:
    """Tests for F1-based KQL + LLM Sigma quality."""

    @pytest.fixture()
    def strategy(self, tmp_path: Path) -> F1SigmaStrategy:
        return F1SigmaStrategy(prompts_dir=tmp_path)

    @pytest.fixture()
    def strategy_with_sigma(self, tmp_path: Path) -> F1SigmaStrategy:
        (tmp_path / "sigma_quality_system.j2").write_text("You are a judge.")
        (tmp_path / "sigma_quality_user.j2").write_text(
            "Rule:\n{{ pred_rule }}\nContext: {{ context_type }}\n{{ evaluation_context }}"
        )
        return F1SigmaStrategy(prompts_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_no_patterns_no_sigma(self, strategy: F1SigmaStrategy) -> None:
        ctx = _make_ctx(submission="{}")
        result = await strategy.score(ctx, None)
        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_f1_from_tool_steps(self, strategy: F1SigmaStrategy) -> None:
        """F1 is computed from execute_kql_query tool step outputs."""
        criteria = DomainCriteria(
            regex_patterns={"FileName": r"cmd\.exe"},
        )
        # Build a tool step with Kusto-formatted output
        kusto_output = json.dumps({
            "stdout": json.dumps({
                "Tables": [{
                    "Columns": [{"ColumnName": "FileName"}],
                    "Rows": [["cmd.exe"]],
                }]
            })
        })
        step = _make_tool_step(
            tool_name="execute_kql_query",
            output=kusto_output,
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, submission="{}")
        result = await strategy.score(ctx, None)
        # F1 should be positive (×5 weight)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_sigma_with_llm_mock(
        self, strategy_with_sigma: F1SigmaStrategy
    ) -> None:
        criteria = DomainCriteria(
            regex_patterns={},
            detection_objective="Detect credential dumping",
            model="openai/gpt-4",
        )
        submission = json.dumps({
            "sigma_rule": "title: Cred Dump\ndetection:\n  condition: selection",
        })
        ctx = _make_ctx(submission=submission, criteria=criteria)

        mock_response = MagicMock()
        mock_response.completion = json.dumps({
            "syntax_score": 0.8,
            "specificity": 0.9,
        })
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await strategy_with_sigma.score(ctx, None)

        # sigma_quality = 0.25*0.8 + 0.75*0.9 = 0.875
        # combined = 0*5 + 0.875*1.5 = 1.3125, capped to max_score=1.0
        assert float(str(result.value)) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_sigma_extraction_from_regex_fallback(
        self, strategy_with_sigma: F1SigmaStrategy
    ) -> None:
        """sigma_rule extracted from submission via regex when JSON parse fails."""
        criteria = DomainCriteria(
            detection_objective="Detect persistence",
            model="openai/gpt-4",
        )
        # Submission with malformed JSON but regex-extractable sigma_rule
        submission = '{"sigma_rule": "title: Persistence\\ndetection:\\n  condition: sel", broken'
        ctx = _make_ctx(submission=submission, criteria=criteria)

        mock_response = MagicMock()
        mock_response.completion = '{"syntax_score": 0.5, "specificity": 0.6}'
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await strategy_with_sigma.score(ctx, None)

        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_explanation_format(self, strategy: F1SigmaStrategy) -> None:
        ctx = _make_ctx(submission="{}")
        result = await strategy.score(ctx, None)
        assert result.explanation is not None
        assert "F1=" in result.explanation
        assert "Sigma=" in result.explanation

    @pytest.mark.asyncio
    async def test_value_capped_at_max_score(
        self, strategy_with_sigma: F1SigmaStrategy
    ) -> None:
        """Combined score should not exceed max_score."""
        criteria = DomainCriteria(
            regex_patterns={"F": r"v"},
            detection_objective="Detect X",
            model="openai/gpt-4",
        )
        # Create tool step with perfect F1
        kusto_output = json.dumps({
            "stdout": json.dumps({
                "Tables": [{
                    "Columns": [{"ColumnName": "F"}],
                    "Rows": [["v"]],
                }]
            })
        })
        step = _make_tool_step(tool_name="execute_kql_query", output=kusto_output)
        submission = json.dumps({"sigma_rule": "title: X\ndetection:\n  condition: sel"})
        ctx = _make_ctx(
            tool_steps=(step,),
            criteria=criteria,
            submission=submission,
            max_score=1.0,
        )

        mock_response = MagicMock()
        mock_response.completion = '{"syntax_score": 1.0, "specificity": 1.0}'
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await strategy_with_sigma.score(ctx, None)

        assert float(str(result.value)) <= 1.0

    @pytest.mark.asyncio
    async def test_stdout_nested_under_data(self, strategy: F1SigmaStrategy) -> None:
        """Kusto output with stdout nested under data field is parsed correctly."""
        criteria = DomainCriteria(regex_patterns={"FileName": r"cmd\.exe"})
        kusto_output = json.dumps({
            "data": {
                "stdout": json.dumps({
                    "Tables": [{
                        "Columns": [{"ColumnName": "FileName"}],
                        "Rows": [["cmd.exe"]],
                    }]
                })
            }
        })
        step = _make_tool_step(tool_name="execute_kql_query", output=kusto_output)
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, submission="{}")
        result = await strategy.score(ctx, None)
        assert float(str(result.value)) > 0.0

    @pytest.mark.asyncio
    async def test_malformed_kusto_output_skipped(self, strategy: F1SigmaStrategy) -> None:
        """Invalid tool output JSON doesn't crash, step is skipped."""
        criteria = DomainCriteria(regex_patterns={"F": r"v"})
        step = _make_tool_step(
            tool_name="execute_kql_query",
            output="this is not json at all",
        )
        ctx = _make_ctx(tool_steps=(step,), criteria=criteria, submission="{}")
        result = await strategy.score(ctx, None)
        # No valid query results parsed, so F1=0
        assert result.value == pytest.approx(0.0)
