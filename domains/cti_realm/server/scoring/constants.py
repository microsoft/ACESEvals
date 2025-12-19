"""
CTI Realm Scoring Constants

Configuration loaders and utilities for CTI Realm-specific scoring.
Separated from main saber_scorer.py to keep domain-specific logic isolated.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from saber.logging_config import LogCategory, get_saber_logger

logger = get_saber_logger(LogCategory.EVALUATION, __name__)


class CTIRealmStepEvaluationStrategy(str, Enum):
    """
    CTI Realm-specific evaluation strategies for subtask step evaluation.

    These strategies are specific to the CTI Realm domain and implement
    the 5-checkpoint evaluation framework (C0-C4) for cyber threat intelligence tasks:
    - CTI_TOOL_LLM (C0): Two-phase CTI tool detection + LLM quality assessment
    - TRAJECTORY_JACCARD (C1): Trajectory regex search with Jaccard similarity for MITRE techniques
    - TOOL_CALL_JACCARD (C2): Tool call parameter extraction with Jaccard similarity for data sources
    - F1_SIGMA_SCORING (C4): F1-based KQL validation + LLM Sigma rule quality evaluation
    """

    CTI_TOOL_LLM = "cti_tool_llm"
    """C0: Two-phase CTI tool detection + LLM quality assessment (subtasks only)"""

    TRAJECTORY_JACCARD = "trajectory_jaccard"
    """C1: Search entire trajectory with regex patterns, calculate Jaccard similarity (subtasks only)"""

    TOOL_CALL_JACCARD = "tool_call_jaccard"
    """C2: Detect tool calls, extract parameters, calculate Jaccard similarity (subtasks only)"""

    F1_SIGMA_SCORING = "f1_sigma_scoring"
    """C4: F1-based KQL scoring combined with LLM Sigma rule evaluation (subtasks only)"""

    def __str__(self) -> str:
        """Return the enum value as string for logging and serialization."""
        return self.value


# Cache for LLM judge prompt configurations
_CTI_THREAT_ALIGNMENT_CONFIG: Optional[Dict[str, Any]] = None
_SIGMA_RULE_QUALITY_CONFIG: Optional[Dict[str, Any]] = None


def load_cti_threat_alignment_config() -> Dict[str, Any]:
    """Load CTI threat alignment prompt configuration with few-shot examples.

    Loads cti_threat_alignment.json which contains few-shot examples for
    evaluating CTI research quality and relevance.

    Returns:
        Dictionary with prompt configuration including few_shots, system, instruction, etc.
    """
    global _CTI_THREAT_ALIGNMENT_CONFIG

    if _CTI_THREAT_ALIGNMENT_CONFIG is not None:
        return _CTI_THREAT_ALIGNMENT_CONFIG

    config_file = Path(__file__).parent.parent / "config" / "tasks" / "cti_detection" / "cti_threat_alignment.json"

    if config_file.exists():
        logger.info(f"Loading CTI threat alignment config from {config_file}")
        with open(config_file, "r") as f:
            _CTI_THREAT_ALIGNMENT_CONFIG = json.load(f)
        return _CTI_THREAT_ALIGNMENT_CONFIG

    logger.warning("cti_threat_alignment.json not found, few-shot examples will not be available")
    _CTI_THREAT_ALIGNMENT_CONFIG = {}
    return _CTI_THREAT_ALIGNMENT_CONFIG


def load_sigma_rule_quality_config() -> Dict[str, Any]:
    """Load Sigma rule quality prompt configuration with few-shot examples.

    Loads sigma_rule_quality.json which contains few-shot examples for
    evaluating Sigma rule syntax and specificity.

    Returns:
        Dictionary with prompt configuration including few_shots, system, instruction, etc.
    """
    global _SIGMA_RULE_QUALITY_CONFIG

    if _SIGMA_RULE_QUALITY_CONFIG is not None:
        return _SIGMA_RULE_QUALITY_CONFIG

    config_file = Path(__file__).parent.parent / "config" / "tasks" / "cti_detection" / "sigma_rule_quality.json"

    if config_file.exists():
        logger.info(f"Loading Sigma rule quality config from {config_file}")
        with open(config_file, "r") as f:
            _SIGMA_RULE_QUALITY_CONFIG = json.load(f)
        return _SIGMA_RULE_QUALITY_CONFIG

    logger.warning("sigma_rule_quality.json not found, few-shot examples will not be available")
    _SIGMA_RULE_QUALITY_CONFIG = {}
    return _SIGMA_RULE_QUALITY_CONFIG


def build_few_shot_examples(config: Dict[str, Any], example_formatter: Callable[[int, Dict[str, Any]], str]) -> str:
    """Build few-shot examples from config using a formatter function.

    This matches the trajectory_scorer.py implementation to ensure consistent
    few-shot prompting for LLM judges.

    Args:
        config: Prompt configuration containing 'few_shots' list
        example_formatter: Function that takes (index, example) and returns formatted string

    Returns:
        Formatted few-shot examples joined with separators
    """
    few_shots = config.get("few_shots", [])
    if not few_shots:
        return ""

    examples = [example_formatter(i + 1, ex) for i, ex in enumerate(few_shots)]
    return "\n\n---\n\n".join(examples)


__all__ = [
    "CTIRealmStepEvaluationStrategy",
    "load_cti_threat_alignment_config",
    "load_sigma_rule_quality_config",
    "build_few_shot_examples",
]
