"""CTI Realm scoring strategies implementing SaberScoringStrategy.

Five strategies:
- TrajectoryAnalysisStrategy  (submission, trajectory_analysis)
- CTIToolLLMStrategy          (subtask C0, cti_tool_llm)
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

from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.scorer import Score

from saber.scoring.context import ScoringContext

from ._kql import score_kql_development
from ._parsing import build_few_shot_examples, parse_model_output
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

    def __init__(self, config_dir: Path) -> None:
        sigma_path = config_dir / "sigma_rule_quality.json"
        self._sigma_config: dict[str, object] = (
            json.loads(sigma_path.read_text()) if sigma_path.exists() else {}
        )

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
        if self._sigma_config:
            model_name = _extra_str(ctx, "model", "openai/azure/gpt-5-mini")
            sigma_quality = await score_sigma_rule(
                predicted, detection_objective, self._sigma_config,
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
# 2. CTIToolLLMStrategy (subtask C0)
# ---------------------------------------------------------------------------


class CTIToolLLMStrategy:
    """Two-phase CTI tool detection + LLM quality assessment."""

    def __init__(self, config_dir: Path) -> None:
        cti_path = config_dir / "cti_threat_alignment.json"
        self._cti_config: dict[str, object] = (
            json.loads(cti_path.read_text()) if cti_path.exists() else {}
        )

    async def score(self, ctx: ScoringContext, renderer: object) -> Score:
        cti_tools = ["get_cti_reports_by_tag", "list_cti_report_tags"]

        # Phase 1: detect CTI tool calls
        tags_searched: list[str] = []
        tools_used: set[str] = set()

        for step in ctx.tool_steps:
            if step.tool_name in cti_tools:
                tools_used.add(step.tool_name)
                if step.tool_name == "get_cti_reports_by_tag":
                    tag = step.tool_input.get("tag")
                    if tag:
                        tags_searched.append(str(tag))

        if not tools_used:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation="No CTI tools detected",
            )

        # Phase 2: LLM quality assessment
        model_name = _extra_str(ctx, "model")
        if not model_name or not self._cti_config:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation="Missing model config or CTI config",
            )

        # Collect reasoning from steps
        reasoning_parts: list[str] = []
        for step in ctx.tool_steps:
            if step.reasoning:
                reasoning_parts.append(step.reasoning)
            if step.assistant_message:
                reasoning_parts.append(step.assistant_message)
        agent_reasoning = "\n\n".join(reasoning_parts) if reasoning_parts else "No agent reasoning found."

        # Get detection description from metadata
        detection_description = str(ctx.metadata.get("description", ""))

        def format_cti_example(idx: int, ex: dict[str, object]) -> str:
            return (
                f"### Example {idx} ({ex['name']})\n"
                f"Detection Objective: {ex['detection_objective']}\n"
                f"CTI Tags Searched: {ex['tags_searched']}\n"
                f"Agent's Reasoning: {ex['agent_reasoning']}\n\n"
                f"Critique:\n{ex['critique']}\n\n"
                f'Score:\n{{"score": {ex["score"]}, "reasoning": "{str(ex["critique"])[:100]}..."}}'
            )

        few_shots_text = build_few_shot_examples(self._cti_config, format_cti_example)

        system_msg = str(self._cti_config.get("system", "You are evaluating CTI threat intelligence research quality."))
        instruction = str(self._cti_config.get("instruction", ""))
        template = str(self._cti_config.get("template", ""))

        filled_template = template.format(
            detection_description=detection_description,
            tags_searched=", ".join(tags_searched) if tags_searched else "None",
            agent_reasoning=agent_reasoning,
        )

        user_msg = (
            f"{instruction}\n\nHere are examples of the format:\n\n{few_shots_text}\n\n---\n\n"
            f"Now evaluate:\n\n{filled_template}\n\n"
            'Output ONLY a JSON object: {"score": <0.0-1.0>, "reasoning": "<brief>"}'
        )

        model = get_model(model_name)
        response = await model.generate(
            input=[
                ChatMessageSystem(content=system_msg),
                ChatMessageUser(content=user_msg),
            ],
        )
        response_text = response.completion

        match = re.search(r"\{[\s\S]*\}", response_text)
        normalized_score = 0.0
        if match:
            try:
                result = json.loads(match.group(0))
                if "score" in result:
                    normalized_score = min(max(float(result["score"]), 0.0), 1.0)
            except (json.JSONDecodeError, ValueError):
                sm = re.search(r'"?score"?\s*:\s*([0-9.]+)', response_text)
                if sm:
                    normalized_score = min(max(float(sm.group(1)), 0.0), 1.0)

        final = normalized_score * ctx.scorer.max_score
        return Score(
            value=final,
            answer=ctx.submission,
            explanation=f"CTI LLM judge: {normalized_score:.2f} → {final:.2f}",
        )


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

    def __init__(self, config_dir: Path) -> None:
        sigma_path = config_dir / "sigma_rule_quality.json"
        self._sigma_config: dict[str, object] = (
            json.loads(sigma_path.read_text()) if sigma_path.exists() else {}
        )

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
        if sigma_rule and self._sigma_config:
            predicted = parse_model_output(ctx.submission)
            if "sigma_rule" not in predicted:
                predicted["sigma_rule"] = sigma_rule
            model_name = _extra_str(ctx, "model", "openai/azure/gpt-5-mini")
            sigma_quality = await score_sigma_rule(
                predicted,
                detection_objective,
                self._sigma_config,
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
