"""SABER Dual scoring registration module.

This module registers SABER Dual-specific scoring strategies with the SABER scoring registry.
It should be imported by the SABER Dual domain initialization code to make custom scorers available.
"""

from saber.inspect_ai.core.scoring import ScorerMetadata, register_subtask_scorer

from .constants import SaberDualStepEvaluationStrategy
from .blue_team_scorer import score_subtask_blue_team_defense

# Track whether we've already registered to avoid duplicate registration errors
_scorers_registered = False


def register_saber_dual_scorers() -> None:
    """Register SABER Dual-specific scoring methods with the global registry.

    This function should be called during SABER Dual domain initialization to make
    custom scoring strategies available for evaluation.
    
    Safe to call multiple times - will only register once.

    Registers:
    - blue_team_defense: Evaluates blue team blocking decisions with penalty support
    """
    global _scorers_registered
    if _scorers_registered:
        return
    
    # Register blue team defense scorer
    # This scorer analyzes block_ip/isolate_container tool calls and:
    # - Awards points for correctly blocking attackers
    # - Deducts points for blocking legitimate traffic (false positives)
    register_subtask_scorer(
        SaberDualStepEvaluationStrategy.BLUE_TEAM_DEFENSE.value,
        score_subtask_blue_team_defense,
        metadata=ScorerMetadata(uses_llm=False, requires_submission=False),
    )
    
    _scorers_registered = True


# Auto-register on import
register_saber_dual_scorers()
