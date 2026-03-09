"""CTI Realm scoring strategies implementing SaberScoringStrategy.

Five strategies:
- TrajectoryAnalysisStrategy  (submission, trajectory_analysis)
- CTIToolLLMStrategy          (subtask C0, cti_tool_llm)  — thin wrapper around LLMJudgeStrategy
- TrajectoryJaccardStrategy   (subtask C1, trajectory_jaccard)
- ToolCallJaccardStrategy     (subtask C2, tool_call_jaccard)
- F1SigmaStrategy             (subtask C4, f1_sigma_scoring)
"""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path

from inspect_ai.scorer import Score

from saber.scoring.context import ScoringContext

from ._kql import score_kql_development
from ._parsing import parse_model_output
from ._sigma import score_sigma_rule

logger = logging.getLogger("saber.domains.cti_realm.scoring.strategies")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extra(ctx: ScoringContext) -> dict[str, object]:
    """Return model_extra from DomainCriteria (or empty dict)."""
    criteria = ctx.scorer.criteria
    from saber.config.models import DomainCriteria
    if isinstance(criteria, DomainCriteria):
        return criteria.model_extra or {}
    return {}


def _extra_str(ctx: ScoringContext, key: str, default: str = "") -> str:
    """Get a string value from DomainCriteria model_extra."""
    value = _extra(ctx).get(key, default)
    return str(value) if value is not None else default


def _extra_list(ctx: ScoringContext, key: str) -> list[str]:
    """Get a list of strings from DomainCriteria model_extra."""
    value = _extra(ctx).get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _extra_dict(ctx: ScoringContext, key: str) -> dict[str, str]:
    """Get a dict of strings from DomainCriteria model_extra."""
    value = _extra(ctx).get(key, {})
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {}


# ---------------------------------------------------------------------------
# 1. TrajectoryAnalysisStrategy (submission scorer)
# ---------------------------------------------------------------------------


class TrajectoryAnalysisStrategy:
    """Submission-based 5-checkpoint evaluation (C0–C4)."""

    def __init__(self, prompts_dir: Path) -> None:
        sys_path = prompts_dir / "sigma_quality_system.j2"
        usr_path = prompts_dir / "sigma_quality_user.j2"
        self._sigma_system = sys_path.read_text() if sys_path.exists() else ""
        self._sigma_user_tpl = usr_path.read_text() if usr_path.exists() else ""

    async def score(self, ctx: ScoringContext, renderer: object) -> Score:
        expected_techniques = _extra_list(ctx, "expected_techniques")
        expected_data_sources = _extra_list(ctx, "expected_data_sources")
        regex_patterns = _extra_dict(ctx, "regex_patterns")
        detection_objective = _extra_str(ctx, "detection_objective")

        submission = ctx.submission
        predicted = parse_model_output(submission)

        # C0: CTI Report Usage
        c0_score = 0.0
        if "cti_analysis" in predicted or "threat_intelligence" in submission.lower():
            c0_score = 1.25

        # C1: Threat Context (MITRE Techniques) — simple mention search
        c1_score = 0.0
        if expected_techniques:
            found = [t for t in expected_techniques if t.lower() in submission.lower()]
            if found:
                c1_score = (len(found) / len(expected_techniques)) * 0.75

        # C2: Data Exploration — data source mentions
        c2_score = 0.0
        if expected_data_sources:
            found = [s for s in expected_data_sources if s.lower() in submission.lower()]
            if found:
                c2_score = (len(found) / len(expected_data_sources)) * 1.0

        # C3: Query Execution — KQL structure check
        c3_score = 0.0
        kql_query = predicted.get("kql_query", "")
        if kql_query:
            keywords = [kw for kw in ("where", "project", "extend", "summarize", "|") if kw in str(kql_query).lower()]
            if keywords:
                c3_score = 0.5

        trajectory_score = c0_score + c1_score + c2_score + c3_score

        # C4: Detection Quality
        f1 = 0.0
        if regex_patterns:
            sample_data: dict[str, object] = {
                "ground_truth": {"regex_patterns": regex_patterns},
            }
            f1 = score_kql_development(predicted, sample_data)

        sigma_quality = 0.0
        if self._sigma_system:
            model_name = _extra_str(ctx, "model", "openai/azure/gpt-5-mini")
            sigma_quality = await score_sigma_rule(
                predicted,
                detection_objective,
                system_prompt=self._sigma_system,
                user_template=self._sigma_user_tpl,
                model_name=model_name,
            )

        c4_score = (f1 * 5.0) + (sigma_quality * 1.5)

        total = trajectory_score + c4_score
        normalized = min(total / 10.0, 1.0)
        final = normalized * ctx.scorer.max_score

        explanation = (
            f"C0={c0_score:.2f}/1.25 C1={c1_score:.2f}/0.75 "
            f"C2={c2_score:.2f}/1.0 C3={c3_score:.2f}/0.5 "
            f"C4={c4_score:.2f}/6.5 (F1={f1:.3f} Sigma={sigma_quality:.3f}) "
            f"Total={total:.2f}/10 Final={final:.3f}"
        )

        return Score(value=final, answer=submission, explanation=explanation)


# ---------------------------------------------------------------------------
# 2. CTIToolLLMStrategy (subtask C0) — thin wrapper around LLMJudgeStrategy
# ---------------------------------------------------------------------------

# CTI tools that indicate the agent performed threat intelligence research.
_CTI_TOOLS: frozenset[str] = frozenset({"get_cti_reports_by_tag", "list_cti_report_tags"})


class CTIToolLLMStrategy:
    """Two-phase CTI scorer: gate on tool usage, then delegate to LLMJudgeStrategy.

    Phase 1 (cheap): if the agent never called any CTI tools, return 0 immediately.
    Phase 2 (LLM):   build ``LLMJudgeCriteria`` from the ``DomainCriteria`` fields
                      in the YAML and delegate to the built-in ``LLMJudgeStrategy``.

    Required ``DomainCriteria`` extra fields (set in the task YAML):
        model, judge_system_template, judge_user_template

    Optional:
        response_format (default ``continuous``), steps_per_message
    """

    async def score(self, ctx: ScoringContext, renderer: object) -> Score:
        from saber.config.models import DomainCriteria, LLMJudgeCriteria, LLMJudgeResponseFormat
        from saber.scoring.strategies import LLMJudgeStrategy
        from saber.scoring.templates import TemplateRenderer

        # Phase 1: gate — did the agent use any CTI tools?
        if not any(step.tool_name in _CTI_TOOLS for step in ctx.tool_steps):
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation="No CTI tools detected",
            )

        # Phase 2: extract LLM judge fields from DomainCriteria extras
        extras = ctx.scorer.criteria.model_extra or {} if isinstance(ctx.scorer.criteria, DomainCriteria) else {}
        model_name = str(extras.get("model", ""))
        sys_tpl = str(extras.get("judge_system_template", ""))
        usr_tpl = str(extras.get("judge_user_template", ""))

        if not model_name or not sys_tpl or not usr_tpl:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation="Missing model, judge_system_template, or judge_user_template in config",
            )

        # Build LLMJudgeCriteria from the DomainCriteria extras
        fmt_str = str(extras.get("response_format", "continuous"))
        response_format = LLMJudgeResponseFormat(fmt_str)
        steps_per_message = extras.get("steps_per_message")

        llm_criteria = LLMJudgeCriteria(
            model=model_name,
            judge_system_template=sys_tpl,
            judge_user_template=usr_tpl,
            response_format=response_format,
            steps_per_message=int(steps_per_message) if steps_per_message is not None else None,
        )

        # Swap criteria in the ScorerConfig and rebuild context
        new_scorer = ctx.scorer.model_copy(update={"criteria": llm_criteria})
        new_ctx = ctx.model_copy(update={"scorer": new_scorer})

        # Delegate to the built-in LLMJudgeStrategy
        if not isinstance(renderer, TemplateRenderer):
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation="CTIToolLLMStrategy requires a TemplateRenderer",
            )

        return await LLMJudgeStrategy().score(new_ctx, renderer)


# ---------------------------------------------------------------------------
# 3. TrajectoryJaccardStrategy (subtask C1)
# ---------------------------------------------------------------------------


class TrajectoryJaccardStrategy:
    """Search entire trajectory with regex; Jaccard similarity."""

    async def score(self, ctx: ScoringContext, renderer: object) -> Score:
        expected_items = _extra_list(ctx, "expected_items")
        if not expected_items:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation="No expected_items in criteria",
            )

        regex_pattern = _extra_str(ctx, "regex_pattern", r"T\d{4}(?:\.\d{3})?")
        expected_set = {item.upper() for item in expected_items}
        items_found: set[str] = set()

        for step in ctx.tool_steps:
            texts = [
                step.output,
                str(step.tool_input),
                step.assistant_message or "",
                step.reasoning or "",
            ]
            for text in texts:
                matches = re.findall(regex_pattern, text, re.IGNORECASE)
                items_found.update(m.upper() for m in matches)

        matched = items_found & expected_set
        union = items_found | expected_set
        jaccard = len(matched) / len(union) if union else 0.0
        value = jaccard * ctx.scorer.max_score

        return Score(
            value=value,
            answer=ctx.submission,
            explanation=(
                f"Jaccard={jaccard:.3f} "
                f"(matched={len(matched)}, found={len(items_found)}, expected={len(expected_set)})"
            ),
        )


# ---------------------------------------------------------------------------
# 4. ToolCallJaccardStrategy (subtask C2)
# ---------------------------------------------------------------------------


class ToolCallJaccardStrategy:
    """Detect tool calls, extract params, Jaccard similarity."""

    async def score(self, ctx: ScoringContext, renderer: object) -> Score:
        expected_tools = _extra_list(ctx, "expected_tools")
        expected_items = _extra_list(ctx, "expected_items")
        param_name = _extra_str(ctx, "param_name", "table")

        if not expected_tools or not expected_items:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation="Missing expected_tools or expected_items",
            )

        if isinstance(expected_tools, str):
            expected_tools = [expected_tools]

        expected_set = {item.lower() for item in expected_items}
        items_found: set[str] = set()

        for step in ctx.tool_steps:
            if step.tool_name not in expected_tools:
                continue
            param_value = step.tool_input.get(param_name, "")
            if param_value:
                val_lower = str(param_value).lower()
                if val_lower in expected_set:
                    items_found.add(val_lower)

        if not items_found and not expected_set:
            jaccard = 1.0
        elif not items_found or not expected_set:
            jaccard = 0.0
        else:
            union = items_found | expected_set
            jaccard = len(items_found & expected_set) / len(union) if union else 0.0

        value = jaccard * ctx.scorer.max_score
        return Score(
            value=value,
            answer=ctx.submission,
            explanation=(
                f"Jaccard={jaccard:.3f} "
                f"(found={len(items_found)}, expected={len(expected_set)})"
            ),
        )


# ---------------------------------------------------------------------------
# 5. F1SigmaStrategy (subtask C4)
# ---------------------------------------------------------------------------


class F1SigmaStrategy:
    """F1-based KQL validation + LLM Sigma rule quality."""

    def __init__(self, prompts_dir: Path) -> None:
        sys_path = prompts_dir / "sigma_quality_system.j2"
        usr_path = prompts_dir / "sigma_quality_user.j2"
        self._sigma_system = sys_path.read_text() if sys_path.exists() else ""
        self._sigma_user_tpl = usr_path.read_text() if usr_path.exists() else ""

    async def score(self, ctx: ScoringContext, renderer: object) -> Score:
        regex_patterns = _extra_dict(ctx, "regex_patterns")
        detection_objective = _extra_str(ctx, "detection_objective")

        # --- extract sigma_rule from submission ---
        sigma_rule: str | None = None
        try:
            submission_json = json.loads(ctx.submission)
            sigma_rule = submission_json.get("sigma_rule")
        except json.JSONDecodeError:
            m = re.search(
                r'"sigma_rule"\s*:\s*"((?:[^"\\]|\\.)*)"', ctx.submission, re.DOTALL
            )
            if m:
                sigma_rule = m.group(1).replace("\\n", "\n").replace("\\t", "\t")

        # --- extract KQL query results from execute_kql_query tool steps ---
        query_results: list[dict[str, object]] = []
        for step in ctx.tool_steps:
            if step.tool_name != "execute_kql_query" or not step.output:
                continue
            try:
                output_data = json.loads(step.output)
            except json.JSONDecodeError:
                try:
                    output_data = ast.literal_eval(step.output)
                except (ValueError, SyntaxError):
                    continue

            stdout = None
            if isinstance(output_data, dict):
                stdout = output_data.get("stdout")
                if not stdout:
                    data_field = output_data.get("data", {})
                    if isinstance(data_field, dict):
                        stdout = data_field.get("stdout", "")

            if not stdout:
                continue

            if isinstance(stdout, dict):
                kusto_result = stdout
            else:
                stdout_str = str(stdout).strip()
                if not stdout_str:
                    continue
                try:
                    kusto_result = json.loads(stdout_str)
                except json.JSONDecodeError:
                    continue

            tables = kusto_result.get("Tables", [])
            if tables:
                table_0 = tables[0]
                rows = table_0.get("Rows", [])
                columns = table_0.get("Columns", [])
                col_names = [c["ColumnName"] for c in columns]
                for row in rows:
                    query_results.append(
                        dict(zip(col_names, row))
                    )

        # --- F1 scoring (5.0 weight) ---
        f1_score = 0.0
        if regex_patterns and query_results:
            total_matches = 0
            for row in query_results:
                row_matches = 0
                for field, pattern in regex_patterns.items():
                    for rf, rv in row.items():
                        if rf.lower() == field.lower():
                            if re.search(pattern, str(rv), re.IGNORECASE):
                                row_matches += 1
                if row_matches > 0:
                    total_matches += 1

            total_rows = len(query_results)
            precision = total_matches / total_rows if total_rows > 0 else 0.0
            # Compute real recall: what fraction of pattern fields were matched
            fields_found: set[str] = set()
            for row in query_results:
                for field, pattern in regex_patterns.items():
                    for rf, rv in row.items():
                        if rf.lower() == field.lower():
                            if re.search(pattern, str(rv), re.IGNORECASE):
                                fields_found.add(field)
            recall = len(fields_found) / len(regex_patterns) if regex_patterns else 0.0
            if precision + recall > 0:
                f1_score = 2 * precision * recall / (precision + recall)

        # --- Sigma quality scoring (1.5 weight) ---
        sigma_quality = 0.0
        if sigma_rule and self._sigma_system:
            predicted = parse_model_output(ctx.submission)
            if "sigma_rule" not in predicted:
                predicted["sigma_rule"] = sigma_rule
            model_name = _extra_str(ctx, "model", "openai/azure/gpt-5-mini")
            sigma_quality = await score_sigma_rule(
                predicted,
                detection_objective,
                system_prompt=self._sigma_system,
                user_template=self._sigma_user_tpl,
                model_name=model_name,
            )

        combined = (f1_score * 5.0) + (sigma_quality * 1.5)
        value = min(combined, ctx.scorer.max_score)

        return Score(
            value=value,
            answer=ctx.submission,
            explanation=(
                f"F1={f1_score:.3f} (×5={f1_score*5:.2f}) "
                f"Sigma={sigma_quality:.3f} (×1.5={sigma_quality*1.5:.2f}) "
                f"Combined={combined:.2f}"
            ),
        )


__all__ = [
    "TrajectoryAnalysisStrategy",
    "CTIToolLLMStrategy",
    "TrajectoryJaccardStrategy",
    "ToolCallJaccardStrategy",
    "F1SigmaStrategy",
]
