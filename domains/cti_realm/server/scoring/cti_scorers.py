"""
CTI Realm Domain-Specific Scoring Methods

CTI-specific scoring strategies for the CTI detection challenge.
These implement the sophisticated 5-checkpoint evaluation system:
- C0: CTI Report Usage (cti_tool_llm)
- C1: Threat Context - MITRE techniques (trajectory_jaccard)
- C2: Data Exploration - data sources (tool_call_jaccard)
- C3: Query Execution - KQL iterations (tool_call_count - in standard scorers)
- C4: Detection Quality - F1 + Sigma (f1_sigma_scoring)
- Trajectory Analysis - submission-based checkpoint evaluation (trajectory_analysis)
"""

import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.solver import TaskState

from saber.logging_config import LogCategory, get_saber_logger
from saber.models.rest.evaluation import (
    EpisodeStepsResponse,
    EpisodeSubmissionResponse,
    StepEvaluation,
    SubmissionEvaluationCriteriaResponse,
    SubtaskEvaluationCriteriaResponse,
)

from .constants import build_few_shot_examples, load_cti_threat_alignment_config, load_sigma_rule_quality_config
from .parsing_utils import parse_model_output
from .scorer import _score_kql_development, _score_sigma_rule

logger = get_saber_logger(LogCategory.EVALUATION, __name__)


async def score_submission_trajectory_analysis(
    submission_data: EpisodeSubmissionResponse,
    criteria: SubmissionEvaluationCriteriaResponse,
    session_manager: Any,
    state: TaskState,
) -> tuple[float, str]:
    """
    CTI Realm trajectory analysis scoring using submission-based evaluation.

    Analyzes the agent's final submission using the sophisticated 5-checkpoint system:
    - C0: CTI Report Usage - Evidence of CTI analysis in submission
    - C1: Threat Context - MITRE techniques mentioned in submission
    - C2: Data Exploration - Data sources referenced in submission
    - C3: Query Execution - KQL query structure and validity
    - C4: Detection Quality - F1 score + Sigma rule quality using original CTI scoring

    Uses same scoring logic as original CTI Realm scorer but evaluates final submission
    instead of analyzing episode trajectory steps.

    Args:
        submission_data: Episode submission data containing agent's final answer
        criteria: Submission evaluation criteria with expected patterns
        session_manager: Client session manager
        state: Task state

    Returns:
        Tuple of (score, explanation) where score reflects sophisticated checkpoint analysis
    """
    try:

        # Parse the agent's final submission using CTI's sophisticated checkpoint system
        model_output = submission_data.submission if hasattr(submission_data, "submission") else ""
        if not model_output:
            logger.warning("No submission data available for trajectory analysis")
            return 0.0, "trajectory_analysis=0.0 (no submission data)"
        logger.info("Submission Data is: %s", model_output)
        # Parse submission using CTI's parsing utilities
        predicted = parse_model_output(model_output)
        if not predicted:
            logger.warning("Could not parse submission as valid JSON")
            return 0.0, "trajectory_analysis=0.0 (invalid submission format)"

        # Extract evaluation criteria
        expected_techniques = criteria.criteria.get("expected_techniques", [])
        expected_data_sources = criteria.criteria.get("expected_data_sources", [])
        regex_patterns = criteria.criteria.get("regex_patterns", {})

        # Build expected/sample data structure for scoring functions
        sample_data = {
            "ground_truth": {
                "mitre_techniques": expected_techniques,
                "data_sources": expected_data_sources,
                "regex_patterns": regex_patterns,
            },
            "subtasks": {"regex_patterns": regex_patterns},
        }

        # **C0: CTI Report Usage** - Check if submission shows evidence of CTI analysis
        c0_score = 0.0
        c0_achieved = False
        cti_analysis_found = "cti_analysis" in predicted
        threat_intel_mentioned = "threat_intelligence" in model_output.lower()

        if cti_analysis_found or threat_intel_mentioned:
            c0_score = 1.25  # Max score for C0
            c0_achieved = True
            logger.info(
                f"C0 (CTI Report Usage) ACHIEVED: {c0_score}/1.25",
                extra={
                    "cti_analysis_in_predicted": cti_analysis_found,
                    "threat_intelligence_mentioned": threat_intel_mentioned,
                    "event": "c0_evaluation",
                },
            )
        else:
            logger.info(
                f"C0 (CTI Report Usage) NOT ACHIEVED: {c0_score}/1.25",
                extra={
                    "cti_analysis_in_predicted": cti_analysis_found,
                    "threat_intelligence_mentioned": threat_intel_mentioned,
                    "event": "c0_evaluation",
                },
            )

        # **C1: Threat Context (MITRE Techniques)** - Check for expected techniques in submission
        c1_score = 0.0
        c1_achieved = False
        techniques_mentioned = []

        if expected_techniques:
            for technique in expected_techniques:
                if technique.lower() in model_output.lower():
                    techniques_mentioned.append(technique)

            if techniques_mentioned:
                # Jaccard similarity scoring like original
                jaccard_score = len(techniques_mentioned) / len(expected_techniques)
                c1_score = jaccard_score * 0.75  # Max weight for C1
                c1_achieved = jaccard_score > 0
                logger.info(
                    f"C1 (Threat Context) ACHIEVED: {c1_score:.2f}/0.75 (Jaccard: {jaccard_score:.2f})",
                    extra={
                        "expected_techniques": expected_techniques,
                        "techniques_found": techniques_mentioned,
                        "jaccard_similarity": jaccard_score,
                        "event": "c1_evaluation",
                    },
                )
            else:
                logger.info(
                    f"C1 (Threat Context) NOT ACHIEVED: {c1_score}/0.75 - No techniques found",
                    extra={
                        "expected_techniques": expected_techniques,
                        "techniques_found": [],
                        "event": "c1_evaluation",
                    },
                )
        else:
            logger.info("C1 (Threat Context) SKIPPED: No expected techniques defined", extra={"event": "c1_evaluation"})

        # **C2: Data Exploration** - Check for evidence of data source usage
        c2_score = 0.0
        c2_achieved = False
        sources_mentioned = []

        if expected_data_sources:
            for source in expected_data_sources:
                if source.lower() in model_output.lower():
                    sources_mentioned.append(source)

            if sources_mentioned:
                # Jaccard similarity scoring like original
                jaccard_score = len(sources_mentioned) / len(expected_data_sources)
                c2_score = jaccard_score * 1.0  # Max weight for C2
                c2_achieved = jaccard_score > 0
                logger.info(
                    f"C2 (Data Exploration) ACHIEVED: {c2_score:.2f}/1.0 (Jaccard: {jaccard_score:.2f})",
                    extra={
                        "expected_data_sources": expected_data_sources,
                        "sources_found": sources_mentioned,
                        "jaccard_similarity": jaccard_score,
                        "event": "c2_evaluation",
                    },
                )
            else:
                logger.info(
                    f"C2 (Data Exploration) NOT ACHIEVED: {c2_score}/1.0 - No data sources found",
                    extra={
                        "expected_data_sources": expected_data_sources,
                        "sources_found": [],
                        "event": "c2_evaluation",
                    },
                )
        else:
            logger.info(
                "C2 (Data Exploration) SKIPPED: No expected data sources defined", extra={"event": "c2_evaluation"}
            )

        # **C3: Query Execution** - Check for KQL query presence and structure
        c3_score = 0.0
        c3_achieved = False
        kql_query_present = "kql_query" in predicted and predicted["kql_query"]

        if kql_query_present:
            query = predicted["kql_query"]
            # Basic query validation
            keywords_found = [kw for kw in ["where", "select", "from", "|"] if kw in query.lower()]

            if keywords_found:
                c3_score = 0.5  # Max weight for C3
                c3_achieved = True
                logger.info(
                    f"C3 (Query Execution) ACHIEVED: {c3_score}/0.5",
                    extra={
                        "kql_query_length": len(query),
                        "keywords_found": keywords_found,
                        "query_preview": query[:200] if len(query) > 200 else query,
                        "event": "c3_evaluation",
                    },
                )
            else:
                logger.info(
                    f"C3 (Query Execution) NOT ACHIEVED: {c3_score}/0.5 - No valid KQL keywords",
                    extra={
                        "kql_query_length": len(query),
                        "keywords_checked": ["where", "select", "from", "|"],
                        "event": "c3_evaluation",
                    },
                )
        else:
            logger.info(
                f"C3 (Query Execution) NOT ACHIEVED: {c3_score}/0.5 - No KQL query in submission",
                extra={
                    "kql_query_present": kql_query_present,
                    "predicted_keys": list(predicted.keys()),
                    "event": "c3_evaluation",
                },
            )

        # Calculate trajectory score
        trajectory_score = c0_score + c1_score + c2_score + c3_score

        # Build checkpoints hit list
        checkpoints_hit = []
        if c0_achieved:
            checkpoints_hit.append("C0")
        if c1_achieved:
            checkpoints_hit.append("C1")
        if c2_achieved:
            checkpoints_hit.append("C2")
        if c3_achieved:
            checkpoints_hit.append("C3")

        # **C4: Detection Quality** - Use sophisticated F1 + Sigma scoring from original
        c4_score = 0.0
        f1_score = 0.0
        sigma_quality = 0.0

        if regex_patterns:
            # Use original CTI KQL development scoring
            logger.info(
                "Starting C4 F1-Score evaluation (KQL Development)",
                extra={
                    "regex_patterns_count": len(regex_patterns),
                    "regex_patterns": regex_patterns,
                    "event": "c4_f1_start",
                },
            )
            f1_score = _score_kql_development(predicted, sample_data)
            logger.info(
                f"C4 F1-Score complete: {f1_score:.2f}/1.0 (weighted: {f1_score * 5.0:.2f}/5.0)",
                extra={"f1_score": f1_score, "f1_weighted": f1_score * 5.0, "event": "c4_f1_complete"},
            )
        else:
            logger.info("C4 F1-Score SKIPPED: No regex patterns defined", extra={"event": "c4_f1_skipped"})

        # Use original CTI Sigma rule scoring with full LLM-as-judge evaluation
        # Need to construct a minimal TaskState-like object for _score_sigma_rule
        try:
            # Create a simple TaskState proxy with detection objective as input_text
            class TaskStateProxy:
                def __init__(self, detection_objective):
                    self.input_text = detection_objective

            # Extract detection objective from criteria or use submission data
            detection_objective = criteria.criteria.get("detection_objective", "")
            if not detection_objective and "detection_objective" in sample_data.get("initial_context", {}):
                detection_objective = sample_data["initial_context"]["detection_objective"]

            state_proxy = TaskStateProxy(detection_objective)

            logger.info(
                "Starting C4 Sigma Quality evaluation (LLM-as-judge)",
                extra={
                    "detection_objective_length": len(detection_objective),
                    "detection_objective_preview": (
                        detection_objective[:200] if len(detection_objective) > 200 else detection_objective
                    ),
                    "sigma_rule_present": "sigma_rule" in predicted,
                    "event": "c4_sigma_start",
                },
            )

            # Call the full _score_sigma_rule with LLM judge
            sigma_quality = await _score_sigma_rule(predicted, sample_data, state_proxy)

            logger.info(
                f"C4 Sigma Quality complete: {sigma_quality:.2f}/1.0 (weighted: {sigma_quality * 1.5:.2f}/1.5)",
                extra={
                    "sigma_quality": sigma_quality,
                    "sigma_weighted": sigma_quality * 1.5,
                    "event": "c4_sigma_complete",
                },
            )
        except Exception as e:
            logger.warning(
                f"Full Sigma scoring failed, using fallback: {e}", extra={"error": str(e), "event": "c4_sigma_fallback"}
            )
            # Fallback to basic structural validation only if full scoring fails
            if "sigma_rule" in predicted:
                sigma_rule = predicted["sigma_rule"]
                if sigma_rule and sigma_rule.strip():
                    has_title = "title:" in sigma_rule.lower()
                    has_detection = "detection:" in sigma_rule.lower()
                    has_condition = "condition:" in sigma_rule.lower()
                    structure_score = (has_title + has_detection + has_condition) / 3.0
                    sigma_quality = min(1.0, structure_score)
                    logger.info(
                        f"C4 Sigma Quality (fallback): {sigma_quality:.2f}/1.0",
                        extra={
                            "has_title": has_title,
                            "has_detection": has_detection,
                            "has_condition": has_condition,
                            "structure_score": structure_score,
                            "event": "c4_sigma_fallback_complete",
                        },
                    )
            else:
                logger.info(
                    "C4 Sigma Quality (fallback): 0.0/1.0 - No sigma_rule in submission",
                    extra={"event": "c4_sigma_fallback_no_rule"},
                )

        # Compute C4 score (65% of total: 6.5 points max)
        c4_score = (f1_score * 5.0) + (sigma_quality * 1.5)
        c4_achieved = c4_score > 0

        logger.info(
            f"C4 (Detection Quality) {'ACHIEVED' if c4_achieved else 'NOT ACHIEVED'}: {c4_score:.2f}/6.5",
            extra={
                "c4_total": c4_score,
                "f1_component": f1_score * 5.0,
                "sigma_component": sigma_quality * 1.5,
                "event": "c4_evaluation",
            },
        )

        # Add C4 to checkpoints if achieved
        if c4_achieved:
            checkpoints_hit.append("C4")

        # Total weighted reward (0-10 scale as in original)
        total_score = trajectory_score + c4_score
        max_total_score = 10.0  # 3.5 (C0-C3) + 6.5 (C4)
        normalized_score = min(total_score / max_total_score, 1.0)

        # Apply to submission max_score
        max_score = criteria.scoring.get("max_score", 1.0)
        final_score = normalized_score * max_score

        # Build detailed explanation matching original CTI Realm format
        explanation = f"""CTI Realm Submission-Based Checkpoint Evaluation:
        C0 (CTI Report Usage): {"✓" if c0_achieved else "✗"} ({c0_score:.2f}/1.25)
        C1 (Threat Context): {"✓" if c1_achieved else "✗"} ({c1_score:.2f}/0.75)
        C2 (Data Exploration): {"✓" if c2_achieved else "✗"} ({c2_score:.2f}/1.0)
        C3 (Query Execution): {"✓" if c3_achieved else "✗"} ({c3_score:.2f}/0.5)
        C4 (Detection Quality): {"✓" if c4_achieved else "✗"} ({c4_score:.2f}/6.5)
        - F1-Score: {f1_score:.2f} (weighted: {f1_score * 5.0:.2f}/5.0)
        - Sigma Quality: {sigma_quality:.2f} (weighted: {sigma_quality * 1.5:.2f}/1.5)

        Trajectory Score (C0-C3): {trajectory_score:.2f}/3.5
        Outcome Score (C4): {c4_score:.2f}/6.5
        Total Weighted Reward: {total_score:.2f}/10.0
        Normalized Score: {normalized_score:.3f}
        Final: {final_score:.3f}/{max_score}"""

        logger.info(
            "CTI Realm submission-based trajectory analysis complete",
            extra={
                "total_score": total_score,
                "final_score": final_score,
                "checkpoints_hit": checkpoints_hit,
                "c0_score": c0_score,
                "c1_score": c1_score,
                "c2_score": c2_score,
                "c3_score": c3_score,
                "c4_score": c4_score,
                "f1_score": f1_score,
                "sigma_quality": sigma_quality,
                "event": "cti_submission_trajectory_analysis_complete",
            },
        )

        return final_score, explanation

    except Exception as e:
        logger.error(f"CTI trajectory analysis failed: {e}", extra={"event": "cti_trajectory_analysis_error"})
        return 0.0, f"trajectory_analysis=0.0 (error: {str(e)})"


async def score_subtask_trajectory_jaccard(
    steps_data: EpisodeStepsResponse,
    criteria: SubtaskEvaluationCriteriaResponse,
    task_context: Any,
    session_manager: Any,
    state: TaskState,
    submission_data: EpisodeSubmissionResponse,
) -> Tuple[float, List[StepEvaluation]]:
    """
    Score subtask by searching entire trajectory for pattern matches (C1: MITRE techniques).

    Searches through all step fields (assistant_message, reasoning, tool_output, tool_input)
    using regex patterns. Calculates Jaccard similarity between found items and expected items.

    Args:
        steps_data: Episode steps data with step objects containing assistant_message, reasoning, etc.
        criteria: Subtask criteria with expected_items and optional regex_pattern

    Returns:
        Tuple of (score, step_evaluations)
    """
    logger.info(
        f"Scoring subtask '{criteria.subtask_id}' using TRAJECTORY_JACCARD strategy",
        extra={
            "subtask_id": criteria.subtask_id,
            "strategy": "TRAJECTORY_JACCARD",
            "max_score": criteria.max_score,
            "event": "scoring_subtask_start",
        },
    )

    # Get expected items and pattern
    expected_items = criteria.criteria.get("expected_items", [])
    if not expected_items:
        logger.warning(
            "trajectory_jaccard strategy requires 'expected_items' in criteria",
            extra={"subtask_id": criteria.subtask_id, "event": "trajectory_jaccard_missing_items"},
        )
        return 0.0, []

    # Get regex pattern (default to MITRE technique pattern)
    regex_pattern = criteria.criteria.get("regex_pattern", r"T\d{4}(?:\.\d{3})?")

    # Normalize expected items
    expected_set = set(item.upper() for item in expected_items)
    items_found = set()

    # Search through all steps in trajectory using step object fields
    for step in steps_data.steps:
        # Search in tool output
        if step.tool_output:
            output_text = str(step.tool_output)
            matches = re.findall(regex_pattern, output_text, re.IGNORECASE)
            items_found.update(m.upper() for m in matches)

        # Search in tool input
        if step.tool_input:
            input_text = str(step.tool_input) if isinstance(step.tool_input, dict) else str(step.tool_input)
            matches = re.findall(regex_pattern, input_text, re.IGNORECASE)
            items_found.update(m.upper() for m in matches)

        # Search in assistant message
        if step.assistant_message:
            matches = re.findall(regex_pattern, str(step.assistant_message), re.IGNORECASE)
            items_found.update(m.upper() for m in matches)

        # Search in reasoning
        if step.reasoning:
            matches = re.findall(regex_pattern, str(step.reasoning), re.IGNORECASE)
            items_found.update(m.upper() for m in matches)

    # Filter to only expected items
    matched_items = items_found & expected_set

    # Calculate true Jaccard similarity: |intersection| / |union|
    if matched_items or expected_set:
        union = items_found | expected_set
        jaccard_score = len(matched_items) / len(union) if union else 0.0
    else:
        jaccard_score = 0.0

    score = jaccard_score * criteria.max_score
    achieved = len(matched_items) > 0

    logger.info(
        f"Subtask '{criteria.subtask_id}' TRAJECTORY_JACCARD evaluation complete - Score: {score:.2f}/{criteria.max_score} (Jaccard: {jaccard_score:.3f})",
        extra={
            "subtask_id": criteria.subtask_id,
            "expected_count": len(expected_set),
            "found_count": len(items_found),
            "matched_count": len(matched_items),
            "jaccard_similarity": jaccard_score,
            "score": score,
            "max_score": criteria.max_score,
            "matched_items": list(matched_items),
            "event": "trajectory_jaccard_subtask_complete",
        },
    )

    # Create step evaluations
    step_evals = []
    for step in steps_data.steps:
        step_evals.append(
            StepEvaluation(
                step_number=step.step_number,
                objective_id=criteria.subtask_id,
                objective_type="subtask",
                completed=achieved,
            )
        )

    return score, step_evals


async def score_subtask_tool_call_jaccard(
    steps_data: EpisodeStepsResponse,
    criteria: SubtaskEvaluationCriteriaResponse,
    task_context: Any,
    session_manager: Any,
    state: TaskState,
    submission_data: EpisodeSubmissionResponse,
) -> Tuple[float, List[StepEvaluation]]:
    """
    Score subtask by detecting tool calls and extracting parameters for Jaccard matching (C2: Data sources).

    Searches for specific tool calls and extracts parameter values (e.g., table_name from get_table_schema).
    Calculates Jaccard similarity between extracted values and expected values.

    Similar to score_subtask_tool_call, but uses jaccard similarity to compute score instead of binary score.

    Args:
        steps_data: Episode steps data
        criteria: Subtask criteria with expected_tools, expected_items, and param_name

    Returns:
        Tuple of (score, step_evaluations)
    """
    logger.info(
        f"Scoring subtask '{criteria.subtask_id}' using TOOL_CALL_JACCARD strategy",
        extra={
            "subtask_id": criteria.subtask_id,
            "strategy": "TOOL_CALL_JACCARD",
            "max_score": criteria.max_score,
            "event": "scoring_subtask_start",
        },
    )

    # Get configuration
    expected_tools = criteria.criteria.get("expected_tools", [])
    expected_items = criteria.criteria.get("expected_items", [])
    param_name = criteria.criteria.get("param_name", "table")  # Default for C2

    logger.info(
        f"Configuration loaded for TOOL_CALL_JACCARD: subtask_id={criteria.subtask_id}, expected_tools={expected_tools}, expected_items={expected_items}, param_name={param_name}"
    )

    if not expected_tools or not expected_items:
        logger.warning(
            "tool_call_jaccard strategy requires 'expected_tools' and 'expected_items' in criteria",
            extra={"subtask_id": criteria.subtask_id, "event": "tool_call_jaccard_missing_config"},
        )
        return 0.0, []

    # Normalize
    if isinstance(expected_tools, str):
        expected_tools = [expected_tools]
    expected_set = set(item.lower() for item in expected_items)
    items_found = set()

    logger.info(
        f"Normalized configuration - scanning {len(steps_data.steps)} steps: subtask_id={criteria.subtask_id}, expected_tools_normalized={expected_tools}, expected_set_size={len(expected_set)}"
    )

    # Search for tool calls and extract parameter values
    for step in steps_data.steps:
        tool_params = None

        logger.info(
            f"Processing step {step.step_number}: subtask_id={criteria.subtask_id}, step_tool_name={step.tool_name}, tool_input_type={type(step.tool_input).__name__}, tool_input_preview={str(step.tool_input)[:200] if step.tool_input else None}"
        )

        # Extract tool parameters from input
        if isinstance(step.tool_input, dict):
            tool_params = step.tool_input
            logger.info(
                f"Step {step.step_number}: tool_input is dict - subtask_id={criteria.subtask_id}, tool_params_keys={list(tool_params.keys())}"
            )
        elif isinstance(step.tool_input, str):
            try:
                tool_params = json.loads(step.tool_input)
                logger.info(
                    f"Step {step.step_number}: tool_input parsed from JSON string - subtask_id={criteria.subtask_id}, tool_params_keys={list(tool_params.keys()) if tool_params else []}"
                )
            except json.JSONDecodeError as e:
                logger.info(
                    f"Step {step.step_number}: Failed to parse tool_input as JSON - subtask_id={criteria.subtask_id}, error={str(e)}"
                )

        # Check if this step uses an expected tool (now using step.tool_name directly)
        if step.tool_name in expected_tools and tool_params:
            # Log all available parameters to diagnose extraction issues
            logger.info(
                f"Step {step.step_number}: Tool matched! Available parameters: {list(tool_params.keys())} - subtask_id={criteria.subtask_id}, tool={step.tool_name}, looking_for_param={param_name}"
            )

            # Extract parameter directly from tool_params
            param_value = tool_params.get(param_name, "")

            logger.info(
                f"Step {step.step_number}: Tool matched! Extracting parameter '{param_name}' - subtask_id={criteria.subtask_id}, tool={step.tool_name}, param_value={param_value}, param_found={bool(param_value)}"
            )

            if param_value:
                param_lower = param_value.lower()
                # Only add to items_found if it's in expected_set
                if param_lower in expected_set:
                    items_found.add(param_lower)
                    logger.info(
                        f"Step {step.step_number}: ✓ MATCHED expected item - Parameter added to items_found: {step.tool_name}({param_name}='{param_value}') - subtask_id={criteria.subtask_id}, items_found_count={len(items_found)}"
                    )
                else:
                    logger.info(
                        f"Step {step.step_number}: Parameter found but not in expected_set: {step.tool_name}({param_name}='{param_value}') - subtask_id={criteria.subtask_id}, not added to items_found"
                    )
            else:
                logger.info(
                    f"Step {step.step_number}: Parameter '{param_name}' is empty or missing - subtask_id={criteria.subtask_id}, tool={step.tool_name}"
                )
        else:
            if step.tool_name not in expected_tools:
                logger.debug(
                    f"Step {step.step_number}: Tool '{step.tool_name}' not in expected_tools - subtask_id={criteria.subtask_id}"
                )
            else:
                logger.info(f"Step {step.step_number}: No tool_params extracted - subtask_id={criteria.subtask_id}")

    # Calculate Jaccard similarity
    logger.info(
        f"Computing Jaccard similarity: subtask_id={criteria.subtask_id}, items_found={list(items_found)}, expected_set={list(expected_set)}, items_found_count={len(items_found)}, expected_set_count={len(expected_set)}"
    )

    # Jaccard = |intersection| / |union|
    if not items_found and not expected_set:
        jaccard_score = 1.0
    elif not items_found or not expected_set:
        jaccard_score = 0.0
    else:
        union = items_found | expected_set
        jaccard_score = len(items_found & expected_set) / len(union) if union else 0.0

    score = jaccard_score * criteria.max_score
    achieved = len(items_found) > 0

    logger.info(
        f"Subtask '{criteria.subtask_id}' TOOL_CALL_JACCARD evaluation complete - Score: {score:.2f}/{criteria.max_score} (Jaccard: {jaccard_score:.3f}), expected_count={len(expected_set)}, found_count={len(items_found)}, matched_count={len(items_found)}, items_found={list(items_found)}, expected_set={list(expected_set)}"
    )

    # Create step evaluations
    step_evals = []
    for step in steps_data.steps:
        is_matching_tool = step.tool_name in expected_tools
        step_evals.append(
            StepEvaluation(
                step_number=step.step_number,
                objective_id=criteria.subtask_id,
                objective_type="subtask",
                completed=achieved if is_matching_tool else False,
            )
        )

    return score, step_evals


async def score_subtask_cti_tool_llm(
    steps_data: EpisodeStepsResponse,
    criteria: SubtaskEvaluationCriteriaResponse,
    task_context: Any,
    session_manager: Any,
    state: TaskState,
    submission_data: EpisodeSubmissionResponse,
) -> Tuple[float, List[StepEvaluation]]:
    """
    Score CTI tool usage with two-phase evaluation (C0: CTI Report Usage):
    Phase 1: Deterministic tool detection
    Phase 2: LLM quality assessment (only if tools detected)

    This matches the trajectory_scorer.py approach for C0 evaluation.

    Args:
        steps_data: Episode steps data
        criteria: Step evaluation criteria
        task_context: Task context with detection_objective, question, etc.
        session_manager: Client session manager
        state: Task state

    Returns:
        Tuple of (score, step_evaluations)
    """
    logger.info(
        f"Starting two-phase C0 evaluation for subtask {criteria.subtask_id}",
        extra={"subtask_id": criteria.subtask_id, "event": "cti_tool_llm_start"},
    )

    # Phase 1: Tool Detection
    logger.info(
        "Phase 1: Detecting CTI tool usage",
        extra={"subtask_id": criteria.subtask_id, "event": "phase1_tool_detection_start"},
    )

    cti_tools = ["get_cti_reports_by_tag", "list_cti_report_tags"]
    tools_used = []
    tags_searched = []
    reports_accessed = []
    cti_tool_steps = []

    for step in steps_data.steps:
        # Check if this is a CTI tool (now individual tools instead of wrapped under cti_tools)
        if step.tool_name in cti_tools:
            tools_used.append(step.tool_name)
            cti_tool_steps.append(step.step_number)

            logger.info(
                f"Phase 1: Detected CTI tool '{step.tool_name}' at step {step.step_number}",
                extra={"subtask_id": criteria.subtask_id, "tool": step.tool_name, "step": step.step_number},
            )

            # Extract tags and queries from tool parameters
            tool_params = {}
            if isinstance(step.tool_input, dict):
                tool_params = step.tool_input
            elif isinstance(step.tool_input, str):
                try:
                    tool_params = json.loads(step.tool_input)
                except json.JSONDecodeError:
                    pass

            try:
                if step.tool_name == "get_cti_reports_by_tag":
                    tag = tool_params.get("tag")
                    if tag:
                        tags_searched.append(tag)

            except Exception as e:
                logger.warning(
                    f"Failed to extract CTI tool parameters: {e}",
                    extra={"subtask_id": criteria.subtask_id, "step": step.step_number},
                )

            # Extract report IDs from tool output
            try:
                if step.tool_output and isinstance(step.tool_output, str):
                    title_matches = re.findall(r'"title"\s*:\s*"([^"]+)"', step.tool_output)
                    reports_accessed.extend(title_matches)
            except Exception as e:
                logger.warning(
                    f"Failed to extract reports from tool output: {e}",
                    extra={"subtask_id": criteria.subtask_id, "step": step.step_number},
                )

    # Deduplicate lists
    tools_used = list(set(tools_used))
    reports_accessed = list(set(reports_accessed))

    logger.info(
        f"Phase 1 complete: tools_used={len(tools_used)}, reports_accessed={len(reports_accessed)}",
        extra={
            "subtask_id": criteria.subtask_id,
            "event": "phase1_tool_detection_complete",
            "tools_used": tools_used,
            "reports_accessed": reports_accessed,
            "cti_tool_steps": cti_tool_steps,
        },
    )

    # Early exit if no CTI tools used, return 0 and do not proceed to llm as judge
    if not tools_used:
        logger.info(
            "No CTI tools detected - returning 0.0",
            extra={"subtask_id": criteria.subtask_id, "event": "phase1_no_tools_found"},
        )
        step_evaluations = []
        for step in steps_data.steps:
            step_evaluations.append(
                StepEvaluation(
                    step_number=step.step_number,
                    objective_id=criteria.subtask_id,
                    objective_type="subtask",
                    completed=False,
                )
            )
        return 0.0, step_evaluations

    # Phase 2: LLM Quality Assessment with Few-Shot Examples
    logger.info(
        "Phase 2: Evaluating CTI research quality with LLM",
        extra={"subtask_id": criteria.subtask_id, "event": "phase2_llm_eval_start"},
    )

    # Load CTI threat alignment config with few-shot examples
    cti_config = load_cti_threat_alignment_config()

    logger.info(
        f"Loaded CTI config with keys: {list(cti_config.keys())}",
        extra={
            "subtask_id": criteria.subtask_id,
            "config_keys": list(cti_config.keys()),
            "few_shots_count": len(cti_config.get("few_shots", [])),
            "system_preview": cti_config.get("system", "")[:100],
            "event": "cti_config_loaded",
        },
    )

    model_name = criteria.criteria.get("model")
    if not model_name:
        logger.info(
            "Missing model in step criteria",
            extra={"subtask_id": criteria.subtask_id},
        )
        # Return 0.0 if model not configured
        step_evaluations = []
        for step in steps_data.steps:
            step_evaluations.append(
                StepEvaluation(
                    step_number=step.step_number,
                    objective_id=criteria.subtask_id,
                    objective_type="subtask",
                    completed=False,
                )
            )
        return 0.0, step_evaluations

    # Build the prompt with few-shot examples
    logger.info(
        "Using few-shot prompting with examples from cti_threat_alignment.json",
        extra={"subtask_id": criteria.subtask_id, "few_shot_count": len(cti_config.get("few_shots", []))},
    )

    # Extract agent's reasoning and assistant messages
    reasoning_messages = []
    for step in steps_data.steps:
        if step.reasoning:
            reasoning_messages.append(str(step.reasoning))

    # Extract all assistant messages
    assistant_messages = []
    for step in steps_data.steps:
        if step.assistant_message:
            assistant_messages.append(str(step.assistant_message))

    # Combine reasoning and messages for context
    combined_context = []
    if reasoning_messages:
        combined_context.append("=== Agent Reasoning ===")
        combined_context.extend(reasoning_messages)
    if assistant_messages:
        combined_context.append("\n=== Agent Messages ===")
        combined_context.extend(assistant_messages)

    if combined_context:
        agent_reasoning = "\n\n".join(combined_context)
    else:
        agent_reasoning = "No agent reasoning or messages found."

    # Build few-shot examples using the same format as trajectory_scorer
    def format_cti_example(idx: int, ex: Dict[str, Any]) -> str:
        return f"""### Example {idx} ({ex["name"]})
        Detection Objective: {ex["detection_objective"]}
        CTI Tags Searched: {ex["tags_searched"]}
        Agent's Reasoning: {ex["agent_reasoning"]}

        Critique:
        {ex["critique"]}

        Score:
        {{"score": {ex["score"]}, "reasoning": "{ex["critique"][:100]}..."}}"""

    few_shots_text = build_few_shot_examples(cti_config, format_cti_example)

    logger.info(
        f"Few-shot examples built: {len(few_shots_text)} chars",
        extra={
            "subtask_id": criteria.subtask_id,
            "event": "few_shots_built",
        },
    )

    # Build the complete prompt with few-shot examples
    system_msg = cti_config.get("system", "You are evaluating CTI threat intelligence research quality.")
    instruction = cti_config.get("instruction", "")
    template = cti_config.get("template", "")

    # Fill in the template with actual data
    filled_template = template.format(
        detection_description=task_context.description,
        tags_searched=", ".join(tags_searched) if tags_searched else "None",
        agent_reasoning=agent_reasoning,
    )

    # Construct the full user message with few-shot examples
    user_msg = f"""{instruction}

    Here are examples of the format:

    {few_shots_text}

    ---

    Now evaluate:

    {filled_template}

    Output ONLY a JSON object with this exact format:
    {{"score": <float between 0.0 and 1.0>, "reasoning": "<brief explanation covering tags AND agent reasoning>"}}"""

    # Execute LLM evaluation
    try:
        # Clear state messages and add judge prompts
        state.messages.clear()
        logger.info("system message is: %s", system_msg)
        logger.info("user message is: %s", user_msg)
        state.messages.append(ChatMessageSystem(content=system_msg))
        state.messages.append(ChatMessageUser(content=user_msg))

        # Get model and generate response
        model = get_model(model_name)
        response = await model.generate(state.messages)
        state.output = response

        response_text = state.output.completion

        logger.info(
            "LLM evaluation complete",
            extra={
                "subtask_id": criteria.subtask_id,
                "event": "phase2_llm_eval_complete",
                "response_length": len(response_text),
                "response_preview": response_text[:500] if len(response_text) > 500 else response_text,
            },
        )

        # Parse response - expect JSON with score 0.0-1.0
        match = re.search(r"\{[\s\S]*\}", response_text)
        if match:
            try:
                result = json.loads(match.group(0))

                # Handle different response formats
                if "score" in result:
                    normalized_score = float(result.get("score", 0.0))
                    reasoning = result.get("reasoning", "")
                elif "syntax_score" in result and "specificity" in result:
                    normalized_score = 0.0
                    reasoning = "Incorrect sigma format used, expected cti alignment format."
                    logger.warning(f"Response JSON missing expected fields: {result}")
                else:
                    normalized_score = 0.0
                    reasoning = "Unknown response format"
                    logger.warning(f"Response JSON missing expected fields: {result}")

                # Clamp to [0, 1] and scale to max_score
                normalized_score = min(max(normalized_score, 0.0), 1.0)
                score = normalized_score * criteria.max_score

                logger.info(
                    f"LLM judge score: {normalized_score:.2f} (scaled: {score:.2f}/{criteria.max_score})",
                    extra={"reasoning": reasoning},
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse JSON response: {e}")
                # Fallback: look for score in text
                score_match = re.search(r'"?score"?\s*:\s*([0-9.]+)', response_text)
                if score_match:
                    normalized_score = float(score_match.group(1))
                    normalized_score = min(max(normalized_score, 0.0), 1.0)
                    score = normalized_score * criteria.max_score
                else:
                    score = 0.0
        else:
            logger.warning("No JSON found in response")
            score = 0.0

        completed = score > 0

        # Build step evaluations (mark CTI tool steps)
        step_evaluations = []
        for step in steps_data.steps:
            is_cti_step = step.step_number in cti_tool_steps
            step_evaluations.append(
                StepEvaluation(
                    step_number=step.step_number,
                    objective_id=criteria.subtask_id,
                    objective_type="subtask",
                    completed=completed if is_cti_step else False,
                )
            )

        logger.info(
            f"C0 evaluation complete: score={score}, completed={completed}",
            extra={
                "subtask_id": criteria.subtask_id,
                "event": "cti_tool_llm_complete",
                "score": score,
                "completed": completed,
            },
        )

        return score, step_evaluations

    except Exception as e:
        logger.error(
            f"Phase 2 LLM evaluation failed: {e}",
            extra={
                "subtask_id": criteria.subtask_id,
                "event": "phase2_llm_eval_error",
                "error": str(e),
            },
        )
        # Return 0.0 on error
        step_evaluations = []
        for step in steps_data.steps:
            step_evaluations.append(
                StepEvaluation(
                    step_number=step.step_number,
                    objective_id=criteria.subtask_id,
                    objective_type="subtask",
                    completed=False,
                )
            )
        return 0.0, step_evaluations


async def score_subtask_f1_sigma(
    steps_data: EpisodeStepsResponse,
    criteria: SubtaskEvaluationCriteriaResponse,
    task_context: Any,
    session_manager: Any,
    state: TaskState,
    submission_data: EpisodeSubmissionResponse,
) -> Tuple[float, List[StepEvaluation]]:
    """
    Score subtask using F1-based KQL validation + LLM Sigma rule quality (C4: Detection Quality).

    Combines:
    - F1 score for KQL query validation against regex patterns (5.0 points)
    - LLM-as-judge for Sigma rule quality (1.5 points)

    Extracts KQL query results from execute_kql_query tool outputs in steps,
    and Sigma rule from submission.

    Args:
        steps_data: Episode steps data (contains execute_kql_query outputs)
        criteria: Subtask criteria with regex_patterns and detection_objective
        task_context: Task context
        session_manager: Client session manager
        state: Task state
        submission_data: Episode submission data (final answer with sigma_rule)

    Returns:
        Tuple of (score, step_evaluations)
    """
    logger.info(
        f"Scoring subtask '{criteria.subtask_id}' using F1_SIGMA_SCORING strategy",
        extra={
            "subtask_id": criteria.subtask_id,
            "strategy": "F1_SIGMA_SCORING",
            "max_score": criteria.max_score,
            "event": "scoring_subtask_start",
        },
    )

    # Extract configuration
    regex_patterns = criteria.criteria.get("regex_patterns", {})
    detection_objective = criteria.criteria.get("detection_objective", "")

    # Parse submission to extract sigma_rule
    submission_text = submission_data.submission
    sigma_rule = None
    try:
        # Try JSON parsing first
        submission_json = json.loads(submission_text)
        sigma_rule = submission_json.get("sigma_rule")
    except json.JSONDecodeError:
        # Fallback: try regex extraction
        sigma_match = re.search(r'"sigma_rule"\s*:\s*"((?:[^"\\]|\\.)*)"', submission_text, re.DOTALL)
        if sigma_match:
            sigma_rule = sigma_match.group(1).replace("\\n", "\n").replace("\\t", "\t")

    # Extract KQL query results from execute_kql_query tool outputs in steps
    query_results = []
    kql_query_steps = []

    for step in steps_data.steps:
        # Check if this is an execute_kql_query call (now a direct tool)
        if step.tool_name == "execute_kql_query" and step.tool_output:
            kql_query_steps.append(step.step_number)

            # Parse tool output
            try:
                if isinstance(step.tool_output, dict):
                    output_data = step.tool_output
                elif isinstance(step.tool_output, str):
                    try:
                        output_data = json.loads(step.tool_output)
                    except json.JSONDecodeError:
                        try:
                            output_data = ast.literal_eval(step.tool_output)
                        except (ValueError, SyntaxError) as e:
                            logger.warning(f"Failed to parse tool_output: {e}")
                            continue
                else:
                    output_data = step.tool_output

                # Extract stdout
                if isinstance(output_data, dict):
                    stdout = output_data.get("stdout")

                    if not stdout:
                        data_field = output_data.get("data", {})
                        if isinstance(data_field, dict):
                            stdout = data_field.get("stdout", "")

                    if stdout:
                        # Parse the Kusto result JSON
                        if isinstance(stdout, dict):
                            kusto_result = stdout
                        else:
                            stdout_str = str(stdout).strip()
                            if not stdout_str:
                                logger.warning(f"Empty stdout from step {step.step_number}")
                                continue
                            kusto_result = json.loads(stdout_str)

                        tables = kusto_result.get("Tables", [])

                        if tables:
                            table_0 = tables[0]
                            rows = table_0.get("Rows", [])
                            columns = table_0.get("Columns", [])

                            column_names = [col["ColumnName"] for col in columns]
                            for row in rows:
                                row_dict = {col: val for col, val in zip(column_names, row)}
                                query_results.append(row_dict)

                            logger.info(
                                f"Extracted {len(rows)} query results from step {step.step_number}",
                                extra={"step": step.step_number, "rows": len(rows)},
                            )
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(
                    f"Failed to parse KQL output from step {step.step_number}: {e}",
                    extra={"step": step.step_number, "error": str(e)},
                )

    # Score F1 (5.0 weight) - KQL query validation
    f1_score = 0.0
    if regex_patterns and query_results:
        total_matches = 0
        total_rows = len(query_results)

        for row in query_results:
            row_matches = 0
            for field, pattern in regex_patterns.items():
                for row_field, row_value in row.items():
                    if row_field.lower() == field.lower():
                        try:
                            if re.search(pattern, str(row_value), re.IGNORECASE):
                                row_matches += 1
                        except re.error:
                            logger.warning(f"Invalid regex pattern for {field}: {pattern}")

            if row_matches > 0:
                total_matches += 1

        precision = total_matches / total_rows if total_rows > 0 else 0.0
        recall = precision  # Simplified

        if precision + recall > 0:
            f1_score = 2 * (precision * recall) / (precision + recall)
        else:
            f1_score = 0.0

        logger.info(
            f"F1 KQL scoring complete: {f1_score:.3f} (matched {total_matches}/{total_rows} rows)",
            extra={"f1_score": f1_score, "total_matches": total_matches, "total_rows": total_rows},
        )
    elif regex_patterns:
        logger.warning("No query results found in steps for F1 scoring")

    # Score Sigma quality (1.5 weight) - LLM-as-judge
    sigma_quality = 0.0
    if sigma_rule:
        try:
            sigma_config = load_sigma_rule_quality_config()

            def format_sigma_example(idx: int, ex: Dict[str, Any]) -> str:
                scores = ex.get("scores", {})
                return f"""### Example {idx} ({ex["name"]})
                Detection Objective: {ex["detection_objective"]}

                Sigma Rule:
                {ex["sigma_rule"]}

                Critique:
                {ex["critique"]}

                Scores:
                {{"syntax_score": {scores.get("syntax_score", 0.0)}, "specificity": {scores.get("specificity", 0.0)}}}"""

            few_shots_text = build_few_shot_examples(sigma_config, format_sigma_example)

            system_msg = sigma_config.get("system", "You are a Sigma rule evaluator.")
            instruction = sigma_config.get("instruction", "")
            template = sigma_config.get("template", "")

            filled_template = template.format(
                context_type="Detection Objective",
                evaluation_context=detection_objective,
                pred_rule=sigma_rule,
            )

            user_msg = f"""{instruction}

            Here are examples of the format:

            {few_shots_text}

            ---

            Now evaluate:

            {filled_template}

            Output ONLY a JSON object with this exact format:
            {{"syntax_score": <float between 0.0 and 1.0>, "specificity": <float between 0.0 and 1.0>}}"""

            # Execute LLM evaluation
            state.messages.clear()
            state.messages.append(ChatMessageSystem(content=system_msg))
            state.messages.append(ChatMessageUser(content=user_msg))

            model_name = criteria.criteria.get("model")
            model = get_model(model_name)
            response = await model.generate(state.messages)
            state.output = response

            response_text = state.output.completion

            # Parse score
            try:
                match = re.search(r"\{[\s\S]*\}", response_text)
                if match:
                    scores = json.loads(match.group())

                    if "score" in scores and "syntax_score" not in scores:
                        logger.error("Received wrong format - check for state contamination")
                        sigma_quality = 0.0
                    elif "syntax_score" in scores and "specificity" in scores:
                        syntax = min(max(float(scores.get("syntax_score", 0.0)), 0.0), 1.0)
                        specificity = min(max(float(scores.get("specificity", 0.0)), 0.0), 1.0)

                        weights = sigma_config.get("weights", {"syntax": 0.25, "specificity": 0.75})
                        sigma_quality = (weights["syntax"] * syntax) + (weights["specificity"] * specificity)
                    else:
                        logger.warning("Unexpected JSON format in Sigma quality response")
                        sigma_quality = 0.0
                else:
                    # Fallback
                    syntax_match = re.search(r"syntax[_\s]*score[:\s]+([0-9.]+)", response_text, re.IGNORECASE)
                    spec_match = re.search(r"specificity[:\s]+([0-9.]+)", response_text, re.IGNORECASE)

                    if syntax_match and spec_match:
                        syntax = min(max(float(syntax_match.group(1)), 0.0), 1.0)
                        specificity = min(max(float(spec_match.group(1)), 0.0), 1.0)
                        sigma_quality = (0.25 * syntax) + (0.75 * specificity)

            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse Sigma quality scores: {e}")

            logger.info(f"Sigma quality scoring complete: {sigma_quality:.3f}")
        except Exception as e:
            logger.warning(f"Sigma quality scoring failed: {e}")
    else:
        logger.info("No sigma_rule found in submission, skipping Sigma scoring")

    # Combined score
    score = (f1_score * 5.0) + (sigma_quality * 1.5)
    achieved = score > 0

    logger.info(
        f"Subtask '{criteria.subtask_id}' F1_SIGMA_SCORING complete - Score: {score:.2f}/{criteria.max_score} (F1: {f1_score:.3f}, Sigma: {sigma_quality:.3f})",
        extra={
            "subtask_id": criteria.subtask_id,
            "f1_score": f1_score,
            "sigma_quality": sigma_quality,
            "score": score,
        },
    )

    # Create step evaluations
    step_evals = []
    for step in steps_data.steps:
        is_kql_step = step.step_number in kql_query_steps
        step_evals.append(
            StepEvaluation(
                step_number=step.step_number,
                objective_id=criteria.subtask_id,
                objective_type="subtask",
                completed=achieved if is_kql_step else False,
            )
        )

    return score, step_evals


__all__ = [
    "score_submission_trajectory_analysis",
    "score_subtask_trajectory_jaccard",
    "score_subtask_tool_call_jaccard",
    "score_subtask_cti_tool_llm",
    "score_subtask_f1_sigma",
]
