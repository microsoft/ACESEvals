"""Tests for cti_realm/scoring/_sigma.py — direct score_sigma_rule() unit tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure cti_realm is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cti_realm.scoring._sigma import _DEFAULT_MODEL, score_sigma_rule

SIGMA_CONFIG: dict[str, object] = {
    "system": "You are a Sigma rule evaluator.",
    "instruction": "Evaluate this rule.",
    "template": "Rule:\n{pred_rule}\nContext: {context_type}\n{evaluation_context}",
    "few_shots": [],
    "temperature": 0.0,
    "max_tokens": 100,
    "weights": {"syntax": 0.25, "specificity": 0.75},
}


class TestScoreSigmaRule:
    """Direct tests for score_sigma_rule()."""

    @pytest.mark.asyncio
    async def test_missing_sigma_rule_key_returns_zero(self) -> None:
        """Missing 'sigma_rule' key → returns 0.0."""
        result = await score_sigma_rule({}, "Detect X", SIGMA_CONFIG)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_empty_sigma_rule_value_returns_zero(self) -> None:
        """Empty 'sigma_rule' value → returns 0.0."""
        result = await score_sigma_rule({"sigma_rule": ""}, "Detect X", SIGMA_CONFIG)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_empty_predicted_dict_returns_zero(self) -> None:
        """Empty predicted dict (no sigma_rule key) → returns 0.0."""
        result = await score_sigma_rule({}, "Detect lateral movement", SIGMA_CONFIG)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_valid_json_scores(self) -> None:
        """LLM returns valid JSON → weighted score computed correctly."""
        mock_response = MagicMock()
        mock_response.completion = json.dumps(
            {"syntax_score": 0.8, "specificity": 0.9}
        )
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await score_sigma_rule(
                {"sigma_rule": "title: Test"},
                "Detect X",
                SIGMA_CONFIG,
            )

        # 0.25 * 0.8 + 0.75 * 0.9 = 0.875
        assert result == pytest.approx(0.875)

    @pytest.mark.asyncio
    async def test_no_json_match_falls_back_to_regex(self) -> None:
        """LLM returns no JSON match → falls back to extract_sigma_scores_from_text()."""
        mock_response = MagicMock()
        # No curly braces → regex fallback
        mock_response.completion = "syntax_score: 0.6\nspecificity: 0.7"
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await score_sigma_rule(
                {"sigma_rule": "title: Test\ndetection:\n  condition: sel"},
                "Detect X",
                SIGMA_CONFIG,
            )

        # Regex extracts 0.6 and 0.7 → 0.25*0.6 + 0.75*0.7 = 0.675
        assert result == pytest.approx(0.675)

    @pytest.mark.asyncio
    async def test_json_parse_failure_falls_back_to_regex(self) -> None:
        """LLM JSON parse failure → falls back to regex extraction."""
        mock_response = MagicMock()
        # Has braces but invalid JSON; regex can still find scores
        mock_response.completion = '{broken "syntax_score": 0.5, "specificity": 0.4}'
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await score_sigma_rule(
                {"sigma_rule": "title: Test"},
                "Detect X",
                SIGMA_CONFIG,
            )

        # Regex fallback: syntax=0.5, specificity=0.4 → 0.25*0.5 + 0.75*0.4 = 0.425
        assert result == pytest.approx(0.425)

    @pytest.mark.asyncio
    async def test_generate_raises_exception_propagates(self) -> None:
        """LLM generate() raises exception → propagates to caller."""
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            with pytest.raises(RuntimeError, match="API down"):
                await score_sigma_rule(
                    {"sigma_rule": "title: Test"},
                    "Detect X",
                    SIGMA_CONFIG,
                )

    @pytest.mark.asyncio
    async def test_custom_weights_respected(self) -> None:
        """Custom weights in config (syntax=0.5, specificity=0.5) are respected."""
        custom_config = {
            **SIGMA_CONFIG,
            "weights": {"syntax": 0.5, "specificity": 0.5},
        }
        mock_response = MagicMock()
        mock_response.completion = json.dumps(
            {"syntax_score": 0.8, "specificity": 0.6}
        )
        mock_model = AsyncMock()
        mock_model.generate = AsyncMock(return_value=mock_response)

        with patch("cti_realm.scoring._sigma.get_model", return_value=mock_model):
            result = await score_sigma_rule(
                {"sigma_rule": "title: Test"},
                "Detect X",
                custom_config,
            )

        # 0.5 * 0.8 + 0.5 * 0.6 = 0.7
        assert result == pytest.approx(0.7)

    def test_default_model_constant(self) -> None:
        """Default model should be 'openai/azure/gpt-5-mini'."""
        assert _DEFAULT_MODEL == "openai/azure/gpt-5-mini"
