"""Sigma rule quality scoring via LLM-as-judge.

Ported from server/scoring/scorer.py (_score_sigma_rule).
Uses inspect_ai for model access.  Prompt content is loaded from
Jinja2 templates in ``prompts/judge/``.
"""

from __future__ import annotations

import json
import logging
import re

from inspect_ai.model import GenerateConfig, get_model
from jinja2 import Template

from ._parsing import extract_sigma_scores_from_text

logger = logging.getLogger("saber.domains.cti_realm.scoring.sigma")

# ── defaults ────────────────────────────────────────────────────────
_DEFAULT_MODEL = "openai/azure/gpt-5-mini"
_DEFAULT_TEMPERATURE: float = 0.0
_DEFAULT_MAX_TOKENS: int = 10_000
_DEFAULT_WEIGHTS: dict[str, float] = {"syntax": 0.25, "specificity": 0.75}


async def score_sigma_rule(
    predicted: dict[str, object],
    detection_objective: str,
    *,
    system_prompt: str,
    user_template: str,
    model_name: str = _DEFAULT_MODEL,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    weights: dict[str, float] | None = None,
) -> float:
    """Score a Sigma rule using an LLM judge.

    Args:
        predicted: Parsed model output; must contain ``sigma_rule``.
        detection_objective: The detection objective text.
        system_prompt: Rendered system prompt (from ``sigma_quality_system.j2``).
        user_template: Raw Jinja2 user template string.
        model_name: LLM model name for the judge.
        temperature: Sampling temperature for the judge.
        max_tokens: Maximum tokens for the judge response.
        weights: ``{"syntax": float, "specificity": float}`` score weights.

    Returns:
        Weighted quality score in [0, 1].
    """
    if "sigma_rule" not in predicted:
        return 0.0
    pred_rule = predicted["sigma_rule"]
    if not pred_rule:
        return 0.0

    user_msg = Template(user_template).render(
        context_type="Detection Objective",
        evaluation_context=detection_objective,
        pred_rule=pred_rule,
    )

    judge = get_model(model_name)
    prompt = f"{system_prompt}\n\n{user_msg}"

    response = await judge.generate(
        input=prompt,
        config=GenerateConfig(temperature=temperature, max_tokens=max_tokens),
    )

    match = re.search(r"\{[\s\S]*\}", response.completion)
    if not match:
        syntax, spec = extract_sigma_scores_from_text(response.completion)
    else:
        try:
            scores = json.loads(match.group())
            syntax = float(scores.get("syntax_score", 0.05))
            spec = float(scores.get("specificity", 0.05))
        except (json.JSONDecodeError, ValueError):
            syntax, spec = extract_sigma_scores_from_text(response.completion)

    w = weights or _DEFAULT_WEIGHTS
    return (w["syntax"] * syntax) + (w["specificity"] * spec)
