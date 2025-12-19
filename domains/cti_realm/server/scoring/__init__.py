"""CTI Realm scoring registration module.

This module registers all CTI Realm-specific scoring strategies with the SABER scoring registry.
It should be imported by the CTI Realm domain initialization code to make the custom scorers available.
"""

from saber.inspect_ai.scoring import ScorerMetadata, register_submission_scorer, register_subtask_scorer

# Import CTI Realm specific scorers and constants
from .constants import CTIRealmStepEvaluationStrategy
from .cti_scorers import (
    score_submission_trajectory_analysis,
    score_subtask_cti_tool_llm,
    score_subtask_f1_sigma,
    score_subtask_tool_call_jaccard,
    score_subtask_trajectory_jaccard,
)


def register_cti_realm_scorers() -> None:
    """Register CTI Realm-specific scoring methods with the global registry.

    This function should be called during CTI Realm domain initialization to make
    custom scoring strategies available for evaluation.

    Registers:
    - cti_tool_llm: C0 checkpoint (CTI tool usage with LLM quality assessment)
    - trajectory_jaccard: C1 checkpoint (MITRE technique search with Jaccard similarity)
    - tool_call_jaccard: C2 checkpoint (Data source detection with Jaccard similarity)
    - f1_sigma_scoring: C4 checkpoint (KQL F1 + Sigma LLM scoring)
    """
    # Register trajectory task scorer
    register_submission_scorer("trajectory_analysis", score_submission_trajectory_analysis)
    # Register subtask scorers for CTI Realm 5-checkpoint evaluation (C0-C4)
    # C0: CTI Tool LLM - uses LLM, requires state deepcopy
    register_subtask_scorer(
        CTIRealmStepEvaluationStrategy.CTI_TOOL_LLM.value,
        score_subtask_cti_tool_llm,
        metadata=ScorerMetadata(uses_llm=True, requires_submission=False),
    )
    # C1: Trajectory Jaccard - standard scorer, no LLM
    register_subtask_scorer(
        CTIRealmStepEvaluationStrategy.TRAJECTORY_JACCARD.value,
        score_subtask_trajectory_jaccard,
        metadata=ScorerMetadata(uses_llm=False, requires_submission=False),
    )
    # C2: Tool Call Jaccard - standard scorer, no LLM
    register_subtask_scorer(
        CTIRealmStepEvaluationStrategy.TOOL_CALL_JACCARD.value,
        score_subtask_tool_call_jaccard,
        metadata=ScorerMetadata(uses_llm=False, requires_submission=False),
    )
    # C4: F1 Sigma - uses LLM, requires submission data
    register_subtask_scorer(
        CTIRealmStepEvaluationStrategy.F1_SIGMA_SCORING.value,
        score_subtask_f1_sigma,
        metadata=ScorerMetadata(uses_llm=True, requires_submission=True),
    )


register_cti_realm_scorers()
