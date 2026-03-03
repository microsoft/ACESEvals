"""Tests for cti_realm/scoring/_parsing.py — pure parsing utilities."""

from __future__ import annotations

import json

import pytest

from cti_realm.scoring._parsing import (
    build_few_shot_examples,
    extract_fields_with_regex,
    extract_sigma_scores_from_text,
    parse_model_output,
)


# =====================================================================
# build_few_shot_examples
# =====================================================================


class TestBuildFewShotExamples:
    """Tests for build_few_shot_examples."""

    def test_empty_config(self) -> None:
        result = build_few_shot_examples({}, lambda i, ex: f"shot {i}")
        assert result == ""

    def test_no_few_shots_key(self) -> None:
        result = build_few_shot_examples({"other": "val"}, lambda i, ex: f"shot {i}")
        assert result == ""

    def test_empty_few_shots_list(self) -> None:
        result = build_few_shot_examples({"few_shots": []}, lambda i, ex: f"shot {i}")
        assert result == ""

    def test_single_shot(self) -> None:
        config: dict[str, object] = {"few_shots": [{"name": "example1"}]}
        result = build_few_shot_examples(config, lambda i, ex: f"Shot {i}: {ex['name']}")
        assert result == "Shot 1: example1"

    def test_multiple_shots_separator(self) -> None:
        config: dict[str, object] = {"few_shots": [{"n": "a"}, {"n": "b"}, {"n": "c"}]}
        result = build_few_shot_examples(config, lambda i, ex: f"{i}-{ex['n']}")
        assert result == "1-a\n\n---\n\n2-b\n\n---\n\n3-c"

    def test_formatter_receives_one_based_index(self) -> None:
        indices: list[int] = []
        config: dict[str, object] = {"few_shots": [{"x": 1}, {"x": 2}]}
        build_few_shot_examples(config, lambda i, ex: (indices.append(i), "")[1])
        assert indices == [1, 2]


# =====================================================================
# extract_fields_with_regex
# =====================================================================


class TestExtractFieldsWithRegex:
    """Tests for extract_fields_with_regex."""

    def test_empty_input(self) -> None:
        assert extract_fields_with_regex("") == {}

    def test_extract_sigma_rule_double_quotes(self) -> None:
        text = '{"sigma_rule": "title: Test\\ndetection: foo"}'
        result = extract_fields_with_regex(text)
        assert "sigma_rule" in result
        assert "title: Test" in str(result["sigma_rule"])

    def test_extract_sigma_rule_single_quotes(self) -> None:
        text = "{'sigma_rule': 'title: SingleQuote'}"
        result = extract_fields_with_regex(text)
        assert "sigma_rule" in result
        assert "SingleQuote" in str(result["sigma_rule"])

    def test_extract_kql_query_double_quotes(self) -> None:
        text = '{"kql_query": "DeviceProcessEvents | where Timestamp > ago(1d)"}'
        result = extract_fields_with_regex(text)
        assert "kql_query" in result
        assert "DeviceProcessEvents" in str(result["kql_query"])

    def test_extract_kql_query_single_quotes(self) -> None:
        text = "{'kql_query': 'SecurityEvent | take 10'}"
        result = extract_fields_with_regex(text)
        assert "kql_query" in result
        assert "SecurityEvent" in str(result["kql_query"])

    def test_extract_query_results_json_array(self) -> None:
        text = '{"query_results": [{"col": "val"}]}'
        result = extract_fields_with_regex(text)
        assert "query_results" in result
        assert result["query_results"] == [{"col": "val"}]

    def test_extract_query_results_empty_array(self) -> None:
        text = '{"query_results": []}'
        result = extract_fields_with_regex(text)
        assert "query_results" in result
        assert result["query_results"] == []

    def test_no_matching_fields(self) -> None:
        text = "This is just plain text with no JSON fields."
        assert extract_fields_with_regex(text) == {}

    def test_extract_multiple_fields(self) -> None:
        text = '{"sigma_rule": "rule1", "kql_query": "query1", "query_results": [{"a": 1}]}'
        result = extract_fields_with_regex(text)
        assert len(result) == 3
        assert "sigma_rule" in result
        assert "kql_query" in result
        assert "query_results" in result

    def test_escaped_characters_in_sigma_rule(self) -> None:
        text = r'{"sigma_rule": "title: Test\ndetection:\n  selection:\n    field: \"value\""}'
        result = extract_fields_with_regex(text)
        assert "sigma_rule" in result
        # newlines and quotes should be unescaped
        rule = str(result["sigma_rule"])
        assert "\n" in rule


# =====================================================================
# parse_model_output
# =====================================================================


class TestParseModelOutput:
    """Tests for parse_model_output."""

    def test_valid_json(self) -> None:
        output = json.dumps({"sigma_rule": "test", "kql_query": "q"})
        result = parse_model_output(output)
        assert result["sigma_rule"] == "test"
        assert result["kql_query"] == "q"

    def test_json_with_code_fence(self) -> None:
        output = '```json\n{"sigma_rule": "fenced"}\n```'
        result = parse_model_output(output)
        assert result["sigma_rule"] == "fenced"

    def test_invalid_json_falls_back_to_regex(self) -> None:
        output = 'Here is: {"sigma_rule": "fallback_rule", extra broken'
        result = parse_model_output(output)
        assert "sigma_rule" in result
        assert "fallback_rule" in str(result["sigma_rule"])

    def test_returns_empty_dict_for_non_dict_json(self) -> None:
        result = parse_model_output("[1, 2, 3]")
        assert result == {}

    def test_empty_string(self) -> None:
        result = parse_model_output("")
        assert result == {}

    def test_whitespace_only(self) -> None:
        result = parse_model_output("   \n\n  ")
        assert result == {}

    def test_nested_json(self) -> None:
        data = {"sigma_rule": "r", "query_results": [{"DeviceName": "host1"}]}
        result = parse_model_output(json.dumps(data))
        assert result["sigma_rule"] == "r"
        assert len(result["query_results"]) == 1


# =====================================================================
# extract_sigma_scores_from_text
# =====================================================================


class TestExtractSigmaScoresFromText:
    """Tests for extract_sigma_scores_from_text."""

    def test_default_scores_on_empty_text(self) -> None:
        syntax, spec = extract_sigma_scores_from_text("")
        assert syntax == 0.05
        assert spec == 0.05

    def test_json_style_scores(self) -> None:
        text = '{"syntax_score": 0.9, "specificity": 0.8}'
        syntax, spec = extract_sigma_scores_from_text(text)
        assert syntax == pytest.approx(0.9)
        assert spec == pytest.approx(0.8)

    def test_plain_text_scores(self) -> None:
        text = "syntax_score: 0.75\nspecificity: 0.6"
        syntax, spec = extract_sigma_scores_from_text(text)
        assert syntax == pytest.approx(0.75)
        assert spec == pytest.approx(0.6)

    def test_syntax_only_fallback(self) -> None:
        text = "syntax: 0.5"
        syntax, spec = extract_sigma_scores_from_text(text)
        assert syntax == pytest.approx(0.5)
        assert spec == 0.05  # default

    def test_out_of_range_ignored(self) -> None:
        text = "syntax_score: 1.5\nspecificity: -0.2"
        syntax, spec = extract_sigma_scores_from_text(text)
        # Values outside [0,1] should not be picked—defaults remain
        assert syntax == 0.05
        assert spec == 0.05

    def test_specificity_score_variant(self) -> None:
        text = "specificity_score: 0.65"
        _, spec = extract_sigma_scores_from_text(text)
        assert spec == pytest.approx(0.65)

    def test_integer_scores(self) -> None:
        text = '{"syntax_score": 1, "specificity": 0}'
        syntax, spec = extract_sigma_scores_from_text(text)
        assert syntax == pytest.approx(1.0)
        assert spec == pytest.approx(0.0)
