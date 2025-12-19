"""Scorer for CTI Realm benchmark."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from inspect_ai.model import GenerateConfig, Model, get_model
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer, stderr
from inspect_ai.solver import TaskState

from .parsing_utils import extract_sigma_scores_from_text, parse_model_output
from .trajectory_scorer import analyze_trajectory_checkpoints

logger = logging.getLogger(__name__)

# Get the path to directories
EVAL_DIR = Path(__file__).parent.parent  # server directory
CONFIG_DIR = Path(__file__).parent.parent / "config" / "tasks" / "cti_detection"

# Load LLM judge prompt configurations
_JUDGE_PROMPTS = None


def _build_few_shot_examples(config: Dict[str, Any], example_formatter) -> str:
    """Build few-shot examples from config using a formatter function.

    Args:
        config: Prompt configuration containing 'few_shots'
        example_formatter: Function that takes (index, example) and returns formatted string

    Returns:
        Formatted few-shot examples joined with separators
    """
    few_shots = []
    for idx, example in enumerate(config["few_shots"], 1):
        few_shots.append(example_formatter(idx, example))
    return "\n\n---\n\n".join(few_shots)


def _load_judge_prompts() -> Dict[str, Any]:
    """Load LLM judge prompt configurations from JSON."""
    global _JUDGE_PROMPTS
    if _JUDGE_PROMPTS is None:
        prompts_file = CONFIG_DIR / "llm_judge_prompts.json"
        with open(prompts_file, "r") as f:
            _JUDGE_PROMPTS = json.load(f)
    return _JUDGE_PROMPTS


def _load_datasets(
    stratified_size: int = 75,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Load ground truth answers and samples for specified stratified dataset size.

    Args:
        stratified_size: Size of stratified dataset (25 or 75)

    Returns:
        Tuple of (ground_truth_answers, dataset_samples)
    """
    answers_file = EVAL_DIR / "data" / f"dataset_answers_stratified_{stratified_size}.jsonl"
    samples_file = EVAL_DIR / "data" / f"dataset_samples_stratified_{stratified_size}.jsonl"

    # Load ground truth answers
    ground_truth = {}
    if answers_file.exists():
        with open(answers_file, "r") as f:
            for line in f:
                if line.strip():
                    answer_data = json.loads(line)
                    ground_truth[answer_data["id"]] = answer_data

    # Load dataset samples
    samples = {}
    if samples_file.exists():
        with open(samples_file, "r") as f:
            for line in f:
                if line.strip():
                    sample_data = json.loads(line)
                    samples[sample_data["id"]] = sample_data

    return ground_truth, samples


async def _score_sigma_rule(predicted: Dict[str, Any], expected: Dict[str, Any], state: TaskState) -> float:
    """Score Sigma rule generation quality using LLM-as-judge with critique and weighted scoring (specificity emphasized)."""
    if "sigma_rule" not in predicted:
        return 0.0

    pred_rule = predicted["sigma_rule"]
    if not pred_rule:
        return 0.0

    try:
        # Load prompt configuration
        prompts = _load_judge_prompts()
        config = prompts["sigma_rule_quality"]

        judge = get_model("openai/azure/gpt-5-mini")

        # Use the input text as the evaluation context (contains detection objective)
        evaluation_context = state.input_text or ""
        context_type = "Detection Objective"

        # Build few-shot examples from config
        def format_sigma_example(idx, ex):
            return f"""### Example {idx} ({ex["name"]})
Detection Objective: {ex["detection_objective"]}
Sigma Rule:
{ex["sigma_rule"]}

Critique:
{ex["critique"]}

Scores:
{json.dumps(ex["scores"])}"""

        few_shots_text = _build_few_shot_examples(config, format_sigma_example)

        # Build prompt from template
        prompt = f"""{config["system"]}
{config["instruction"]}

Here are examples of the format:

{few_shots_text}

---

Now evaluate:

{
            config["template"].format(
                context_type=context_type,
                evaluation_context=evaluation_context,
                pred_rule=pred_rule,
            )
        }"""

        response = await judge.generate(
            input=prompt,
            config=GenerateConfig(temperature=config["temperature"], max_tokens=config["max_tokens"]),
        )

        # Extract JSON
        match = re.search(r"\{[\s\S]*\}", response.completion)
        if not match:
            logger.warning("LLM judge returned no JSON, trying regex extraction.")
            logger.debug("LLM Judge Raw Response (no JSON found): %s", response.completion[:500])
            # Fallback: try to extract scores with regex
            syntax, spec = extract_sigma_scores_from_text(response.completion)
        else:
            try:
                scores = json.loads(match.group())
                syntax = float(scores.get("syntax_score", 0.05))
                spec = float(scores.get("specificity", 0.05))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"JSON parsing failed: {e}, trying regex extraction.")
                logger.debug("LLM Judge Raw Response: %s", response.completion[:500])
                # Fallback: try to extract scores with regex
                syntax, spec = extract_sigma_scores_from_text(response.completion)

        # Weighted scoring from config
        weights = config["weights"]
        final_score = (weights["syntax"] * syntax) + (weights["specificity"] * spec)
        return final_score

    except Exception as e:
        logger.warning(f"LLM judge failed: {e}")
        return 0.0


def _validate_linux_device_name(results: List[Dict[str, Any]], sample_id: str) -> bool:
    """Validate that Linux samples have the correct DeviceName.

    Args:
        results: Query results to validate
        sample_id: Sample ID to check if it's a Linux sample

    Returns:
        True if validation passes (non-Linux or has correct DeviceName), False otherwise
    """
    if not sample_id.startswith("linux_"):
        return True

    expected_device_name = "arjunc-cti-vm-3.wqgilo2whriehm0ezwjionoa3a.xx.internal.cloudapp.net"

    # Check if ANY result has the correct DeviceName
    for row in results:
        if isinstance(row, dict):
            device_name = row.get("DeviceName") or row.get("devicename") or row.get("DEVICENAME")
            if device_name == expected_device_name:
                logger.info("[%s] ✓ LINUX CHECK PASSED: Found correct DeviceName", sample_id)
                return True

    logger.error(
        "[%s] ❌ LINUX CHECK FAILED: No results contain required DeviceName '%s'", sample_id, expected_device_name
    )
    return False


def _validate_aks_time_generated(results: List[Dict[str, Any]], sample_id: str) -> bool:
    """Validate that AKS samples have the correct TimeGenerated date.

    Args:
        results: Query results to validate
        sample_id: Sample ID to check if it's an AKS sample

    Returns:
        True if validation passes (non-AKS or has correct date), False otherwise
    """
    if not sample_id.startswith("aks_"):
        return True

    expected_date = "2025-10-31"

    # Check if ANY result has the correct TimeGenerated date
    for row in results:
        if isinstance(row, dict):
            time_generated = row.get("TimeGenerated") or row.get("timegenerated") or row.get("TIMEGENERATED")
            if time_generated:
                # Extract date portion (YYYY-MM-DD) from ISO format like "2025-10-31T16:29:03.8307473Z"
                date_str = str(time_generated).split("T")[0]
                if date_str == expected_date:
                    logger.info(
                        "[%s] ✓ AKS CHECK PASSED: Found correct TimeGenerated date '%s'", sample_id, expected_date
                    )
                    return True

    logger.error(
        "[%s] ❌ AKS CHECK FAILED: No results contain required TimeGenerated date '%s'", sample_id, expected_date
    )
    return False


def _score_kql_development(predicted: Dict[str, Any], expected: Dict[str, Any], sample_id: str = "unknown") -> float:
    """Score KQL query using precision-focused F1 with quality bonuses."""
    logger.info("=" * 60)
    logger.info("KQL DEVELOPMENT SCORING DEBUG")
    logger.info("=" * 60)

    if "query_results" not in predicted:
        logger.error("[%s] No 'query_results' in predicted output", sample_id)
        return 0.0

    # Extract regex patterns from ground_truth structure
    # Structure: {"ground_truth": {"mitre_techniques": [...], "data_sources": [...], "regex_patterns": {...}}}
    if "ground_truth" in expected and isinstance(expected["ground_truth"], dict):
        patterns = expected["ground_truth"].get("regex_patterns", {})
    else:
        # Fallback: try direct regex_patterns key
        patterns = expected.get("regex_patterns", {})

    if not patterns:
        logger.error("[%s] No patterns found in ground truth", sample_id)
        logger.debug("[%s] Expected structure: %s", sample_id, expected)
        return 0.0

    logger.info("[%s] Extracted %d regex patterns from ground truth", sample_id, len(patterns))

    # Parse results
    results = predicted["query_results"]
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except json.JSONDecodeError as e:
            logger.error("[%s] JSON parse failed: %s", sample_id, e)
            return 0.0

    if not isinstance(results, list) or not results:
        logger.error("[%s] Invalid results: %s", sample_id, type(results))
        return 0.0

    # Validate Linux samples have correct DeviceName
    if not _validate_linux_device_name(results, sample_id):
        return 0.0

    # Validate AKS samples have correct TimeGenerated date
    if not _validate_aks_time_generated(results, sample_id):
        return 0.0

    logger.debug("[%s] Ground truth patterns: %s", sample_id, patterns)

    # Helper: Get match details for a row
    def get_row_matches(row: dict) -> tuple[int, list[str]]:
        """Get match count and details for a single row."""
        if not isinstance(row, dict):
            return 0, []

        matches = []
        for field, pattern in patterns.items():
            for row_field, row_value in row.items():
                if row_field.lower() == field.lower():
                    try:
                        # Note: Not using re.IGNORECASE flag since patterns may have inline (?i) flags
                        if re.search(pattern, str(row_value)):
                            matches.append(f"{field}='{row_value}' ✓")
                        else:
                            matches.append(f"{field}='{row_value}' ✗")
                    except re.error as e:
                        logger.warning(
                            "[%s] REGEX ERROR for field '%s': Pattern: %s, Error: %s", sample_id, field, pattern, e
                        )
                        matches.append(f"{field}='{row_value}' ✗ (invalid pattern)")
                    break
        return len([m for m in matches if "✓" in m]), matches

    # Score and log each row
    relevant_rows = []
    perfect_rows = []
    fields_found = set()

    for i, row in enumerate(results):
        if not isinstance(row, dict):
            continue

        match_count, match_details = get_row_matches(row)

        # Determine match type
        if match_count == len(patterns):
            match_type = "PERFECT"
            perfect_rows.append(i)
            relevant_rows.append(i)
        elif match_count > 0:
            match_type = "PARTIAL"
            relevant_rows.append(i)
        else:
            match_type = "NO MATCH"

        # Track fields found
        for field, pattern in patterns.items():
            for row_field, row_value in row.items():
                if row_field.lower() == field.lower():
                    try:
                        # Note: Not using re.IGNORECASE flag since patterns may have inline (?i) flags
                        if re.search(pattern, str(row_value)):
                            fields_found.add(field)
                    except re.error:
                        # Skip invalid patterns in field tracking
                        pass
                    break

        # Log the row
        logger.debug("[%s] Row %d [%s]: %s", sample_id, i, match_type, row)
        for detail in match_details:
            logger.debug("[%s]   %s", sample_id, detail)

    # Calculate metrics with partial credit
    # Precision: relevant rows (any matches) / total rows
    # Recall: fields found across all rows / expected fields
    precision = len(relevant_rows) / len(results) if results else 0.0
    recall = len(fields_found) / len(patterns) if patterns else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Quality bonus: reward perfect matches (up to +20% of base score)
    quality_bonus = min(0.2, 0.05 * len(perfect_rows))
    final_score = min(1.0, f1 * (1.0 + quality_bonus))

    logger.info(
        "[%s] Final: Relevant=%d/%d, Perfect=%d, Fields=%d/%d",
        sample_id,
        len(relevant_rows),
        len(results),
        len(perfect_rows),
        len(fields_found),
        len(patterns),
    )
    logger.info(
        "[%s]   Precision=%.3f, Recall=%.3f, F1=%.3f, Bonus=%.3f, Score=%.3f",
        sample_id,
        precision,
        recall,
        f1,
        quality_bonus,
        final_score,
    )

    return final_score


async def _score_sample(state: TaskState, target: Target, stratified_size: int = 75) -> Score:
    """Common scoring logic for stratified datasets.

    Args:
        state: TaskState containing model output and metadata
        target: Target for scoring
        stratified_size: Size of stratified dataset (25 or 75)

    Returns:
        Score object with evaluation results
    """
    dataset_label = f" (Stratified-{stratified_size})"
    logger.info(f"🎯 === STARTING CTI REALM{dataset_label.upper()} SCORING ===")

    # Load ground truth answers and dataset samples
    ground_truth, dataset_samples = _load_datasets(stratified_size)
    model_output = state.output.completion if state.output else ""

    # Get sample ID from metadata
    sample_id = state.sample_id
    logger.info("[%s] Processing sample", sample_id)

    if not sample_id:
        logger.error("❌ No sample ID found")
        return Score(
            value="FAILED",
            answer="No ground truth found",
            explanation="Could not find ground truth answers for this sample",
        )
    else:
        logger.info("[%s] Found sample in ground truth", sample_id)

    if sample_id not in ground_truth:
        logger.error(f"❌ Sample ID {sample_id} not found in {dataset_type} ground truth")
        return Score(
            value="FAILED",
            answer="Sample not in ground truth",
            explanation=f"Sample {sample_id} not found in {dataset_type} ground truth data",
        )

    expected = ground_truth[sample_id].get("subtasks", {})
    sample_data = dataset_samples.get(sample_id, {})

    predicted = parse_model_output(model_output)

    if not predicted:
        return Score(
            value="FAILED",
            answer=model_output,
            explanation="Could not parse model output as valid JSON",
        )
    else:
        logger.info("[%s] Successfully parsed model output", sample_id)

    # Load judge prompts for trajectory analysis
    judge_prompts = _load_judge_prompts()

    # Analyze trajectory checkpoints (C0-C3)
    trajectory_analysis = await analyze_trajectory_checkpoints(state, sample_data, sample_id, judge_prompts)

    # Calculate C4: Outcome quality
    f1_score = _score_kql_development(predicted, sample_data.get("subtasks", sample_data), sample_id)
    sigma_quality = await _score_sigma_rule(predicted, expected, state)

    # Combined C4 score (65% of total: 6.5 points)
    c4_score = (f1_score * 5.0) + (sigma_quality * 1.5)

    # Total weighted reward
    trajectory_score = trajectory_analysis["trajectory_score"]
    c0_score = trajectory_analysis["c0_score"]
    outcome_score = c4_score
    weighted_reward_total = trajectory_score + outcome_score
    normalized_score = weighted_reward_total / 10.0

    # Add C4 to checkpoints if achieved
    checkpoints_hit = trajectory_analysis["checkpoints_hit"].copy()
    if c4_score > 0:
        checkpoints_hit.append("C4")

    # Create detailed explanation
    explanation = f"""CTI Realm Checkpoint Evaluation{dataset_label}:
C0 (CTI Report Usage): {"✓" if "C0" in checkpoints_hit else "✗"} ({c0_score:.2f}/1.25)
C1 (Threat Context): {"✓" if "C1" in checkpoints_hit else "✗"} ({0.75 if "C1" in checkpoints_hit else 0.0:.2f}/0.75)
C2 (Data Exploration): {"✓" if "C2" in checkpoints_hit else "✗"} ({1.0 if "C2" in checkpoints_hit else 0.0:.2f}/1.0)
C3 (Query Execution - 2+ attempts): {"✓" if "C3" in checkpoints_hit else "✗"} ({0.5 if "C3" in checkpoints_hit else 0.0:.2f}/0.5)
C4 (Detection Quality): {c4_score:.2f}/6.5
  - F1-Score: {f1_score:.2f} (weighted: {f1_score * 5.0:.2f}/5.0)
  - Sigma Quality: {sigma_quality:.2f} (weighted: {sigma_quality * 1.5:.2f}/1.5)

Trajectory Score (C0-C3): {trajectory_score:.2f}/3.5
Outcome Score (C4): {outcome_score:.2f}/6.5
Total Weighted Reward: {weighted_reward_total:.2f}/10.0
Normalized Score: {normalized_score:.2f}"""

    return Score(
        value=normalized_score,
        answer=model_output,
        explanation=explanation,
        metadata={
            "sample_id": sample_id,
            "checkpoints_hit": checkpoints_hit,
            "trajectory_score": trajectory_score,
            "outcome_score": outcome_score,
            "weighted_reward_total": weighted_reward_total,
            "normalized_score": normalized_score,
            "checkpoint_breakdown": {
                "C1_threat_context": 0.75 if "C1" in checkpoints_hit else 0.0,
                "C2_data_exploration": 1.0 if "C2" in checkpoints_hit else 0.0,
                "C3_query_execution": 1.25 if "C3" in checkpoints_hit else 0.0,
                "C4_detection_quality": c4_score,
            },
            "c4_components": {
                "f1_score": f1_score,
                "f1_weighted": f1_score * 5.5,
                "sigma_quality": sigma_quality,
                "sigma_weighted": sigma_quality * 1.5,
                "c4_total": c4_score,
            },
            "checkpoint_steps": trajectory_analysis["checkpoint_steps"],
            "checkpoint_details": trajectory_analysis["checkpoint_details"],
            "steps_total": trajectory_analysis["steps_total"],
        },
    )


@scorer(metrics=[accuracy(), stderr()])
def cti_realm_stratified_25_scorer() -> Scorer:
    """Custom scorer for CTI Realm stratified-25 benchmark."""

    async def score(state: TaskState, target: Target) -> Score:
        """Score the model's performance across all 5 subtasks."""
        return await _score_sample(state, target, stratified_size=25)

    return score


@scorer(metrics=[accuracy(), stderr()])
def cti_realm_stratified_75_scorer() -> Scorer:
    """Custom scorer for CTI Realm stratified-75 benchmark."""

    async def score(state: TaskState, target: Target) -> Score:
        """Score the model's performance across all 5 subtasks."""
        return await _score_sample(state, target, stratified_size=75)

    return score
