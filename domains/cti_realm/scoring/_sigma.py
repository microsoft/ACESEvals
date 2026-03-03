"""Sigma rule quality scoring via LLM-as-judge.

Ported from server/scoring/scorer.py (_score_sigma_rule).
Uses inspect_ai for model access.
"""

import json
import logging
import re

from inspect_ai.model import GenerateConfig, get_model

from ._parsing import build_few_shot_examples, extract_sigma_scores_from_text

logger = logging.getLogger("saber.domains.cti_realm.scoring.sigma")

_DEFAULT_MODEL = "openai/azure/gpt-5-mini"


async def score_sigma_rule(
    predicted: dict[str, object],
    detection_objective: str,
    sigma_config: dict[str, object],
    *,
    model_name: str = _DEFAULT_MODEL,
) -> float:
    """Score a Sigma rule using an LLM judge.

    Args:
        predicted: Parsed model output; must contain ``sigma_rule``.
        detection_objective: The detection objective text.
        sigma_config: Loaded ``sigma_rule_quality.json`` config dict.
        model_name: LLM model name for the judge (default: openai/azure/gpt-5-mini).

    Returns:
        Weighted quality score in [0, 1].
    """
    if "sigma_rule" not in predicted:
        return 0.0
    pred_rule = predicted["sigma_rule"]
    if not pred_rule:
        return 0.0

    judge = get_model(model_name)

    def format_sigma_example(idx: int, ex: dict[str, object]) -> str:
        return (
            f"### Example {idx} ({ex['name']})\n"
            f"Detection Objective: {ex['detection_objective']}\n"
            f"Sigma Rule:\n{ex['sigma_rule']}\n\n"
            f"Critique:\n{ex['critique']}\n\n"
            f"Scores:\n{json.dumps(ex['scores'])}"
        )

    few_shots_text = build_few_shot_examples(sigma_config, format_sigma_example)

    template: str = sigma_config.get("template", "")  # type: ignore[assignment]
    prompt = (
        f"{sigma_config['system']}\n{sigma_config['instruction']}\n\n"
        f"Here are examples of the format:\n\n{few_shots_text}\n\n---\n\n"
        f"Now evaluate:\n\n"
        f"{template.format(context_type='Detection Objective', evaluation_context=detection_objective, pred_rule=pred_rule)}"
    )

    temperature: float = sigma_config.get("temperature", 0.0)  # type: ignore[assignment]
    max_tokens: int = sigma_config.get("max_tokens", 10000)  # type: ignore[assignment]

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

    weights: dict[str, float] = sigma_config.get("weights", {"syntax": 0.25, "specificity": 0.75})  # type: ignore[assignment]
    return (weights["syntax"] * syntax) + (weights["specificity"] * spec)
