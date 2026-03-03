"""Tests for cti_realm/scoring/_kql.py — KQL F1 scoring."""

from __future__ import annotations

import re

import pytest

from cti_realm.scoring._kql import (
    _validate_aks_time_generated,
    _validate_linux_device_name,
    score_kql_development,
)


# =====================================================================
# _validate_linux_device_name
# =====================================================================


class TestValidateLinuxDeviceName:
    EXPECTED_HOST = "arjunc-cti-vm-3.wqgilo2whriehm0ezwjionoa3a.xx.internal.cloudapp.net"

    def test_non_linux_sample_always_passes(self) -> None:
        assert _validate_linux_device_name([], "win_sample") is True

    def test_linux_sample_without_device_name_fails(self) -> None:
        results: list[dict[str, object]] = [{"col": "val"}]
        assert _validate_linux_device_name(results, "linux_test") is False

    def test_linux_sample_with_correct_device_name_passes(self) -> None:
        results: list[dict[str, object]] = [{"DeviceName": self.EXPECTED_HOST}]
        assert _validate_linux_device_name(results, "linux_test") is True

    def test_linux_sample_case_insensitive_field(self) -> None:
        results: list[dict[str, object]] = [{"devicename": self.EXPECTED_HOST}]
        assert _validate_linux_device_name(results, "linux_test") is True

    def test_linux_sample_empty_results(self) -> None:
        assert _validate_linux_device_name([], "linux_test") is False


# =====================================================================
# _validate_aks_time_generated
# =====================================================================


class TestValidateAksTimeGenerated:
    def test_non_aks_sample_always_passes(self) -> None:
        assert _validate_aks_time_generated([], "win_sample") is True

    def test_aks_sample_without_time_generated_fails(self) -> None:
        results: list[dict[str, object]] = [{"col": "val"}]
        assert _validate_aks_time_generated(results, "aks_test") is False

    def test_aks_sample_with_correct_date_passes(self) -> None:
        results: list[dict[str, object]] = [
            {"TimeGenerated": "2025-10-31T12:00:00Z"}
        ]
        assert _validate_aks_time_generated(results, "aks_test") is True

    def test_aks_wrong_date_fails(self) -> None:
        results: list[dict[str, object]] = [
            {"TimeGenerated": "2025-09-15T12:00:00Z"}
        ]
        assert _validate_aks_time_generated(results, "aks_test") is False

    def test_aks_case_insensitive_field(self) -> None:
        results: list[dict[str, object]] = [
            {"timegenerated": "2025-10-31T08:00:00Z"}
        ]
        assert _validate_aks_time_generated(results, "aks_test") is True


# =====================================================================
# score_kql_development
# =====================================================================


class TestScoreKqlDevelopment:
    @staticmethod
    def _sample(patterns: dict[str, str]) -> dict[str, object]:
        return {"ground_truth": {"regex_patterns": patterns}}

    def test_missing_query_results_returns_zero(self) -> None:
        score = score_kql_development({}, self._sample({"f": ".*"}))
        assert score == 0.0

    def test_empty_patterns_returns_zero(self) -> None:
        predicted: dict[str, object] = {"query_results": [{"a": "1"}]}
        assert score_kql_development(predicted, {"ground_truth": {"regex_patterns": {}}}) == 0.0

    def test_no_patterns_key_returns_zero(self) -> None:
        predicted: dict[str, object] = {"query_results": [{"a": "1"}]}
        assert score_kql_development(predicted, {}) == 0.0

    def test_empty_results_list_returns_zero(self) -> None:
        predicted: dict[str, object] = {"query_results": []}
        assert score_kql_development(predicted, self._sample({"f": ".*"})) == 0.0

    def test_string_query_results_parsed(self) -> None:
        import json
        predicted: dict[str, object] = {
            "query_results": json.dumps([{"FileName": "malware.exe"}])
        }
        sample = self._sample({"FileName": r"malware\.exe"})
        score = score_kql_development(predicted, sample)
        assert score > 0.0

    def test_invalid_string_query_results_returns_zero(self) -> None:
        predicted: dict[str, object] = {"query_results": "not json"}
        assert score_kql_development(predicted, self._sample({"f": ".*"})) == 0.0

    def test_exact_match_single_row(self) -> None:
        predicted: dict[str, object] = {
            "query_results": [{"FileName": "malware.exe", "ProcessId": "1234"}]
        }
        patterns = {"FileName": r"malware\.exe", "ProcessId": r"1234"}
        score = score_kql_development(predicted, self._sample(patterns))
        assert score > 0.0

    def test_partial_match(self) -> None:
        predicted: dict[str, object] = {
            "query_results": [
                {"FileName": "malware.exe", "ProcessId": "wrong"},
                {"FileName": "clean.exe", "ProcessId": "5678"},
            ]
        }
        patterns = {"FileName": r"malware\.exe", "ProcessId": r"1234"}
        score = score_kql_development(predicted, self._sample(patterns))
        # Only partial match on FileName in first row, so score should be moderate
        assert 0.0 < score < 1.0

    def test_perfect_rows_quality_bonus(self) -> None:
        predicted: dict[str, object] = {
            "query_results": [
                {"FileName": "mal.exe", "PID": "1"},
                {"FileName": "mal.exe", "PID": "1"},
                {"FileName": "mal.exe", "PID": "1"},
            ]
        }
        patterns = {"FileName": r"mal\.exe", "PID": r"1"}
        score = score_kql_development(predicted, self._sample(patterns))
        # 3 perfect rows → quality_bonus = min(0.2, 0.15)
        assert score > 0.9

    def test_linux_validation_blocks_score(self) -> None:
        predicted: dict[str, object] = {
            "query_results": [{"FileName": "test.sh"}]
        }
        patterns = {"FileName": r"test\.sh"}
        score = score_kql_development(predicted, self._sample(patterns), sample_id="linux_sample")
        assert score == 0.0  # missing DeviceName

    def test_aks_validation_blocks_score(self) -> None:
        predicted: dict[str, object] = {
            "query_results": [{"FileName": "pod.yaml"}]
        }
        patterns = {"FileName": r"pod\.yaml"}
        score = score_kql_development(predicted, self._sample(patterns), sample_id="aks_sample")
        assert score == 0.0  # missing TimeGenerated

    def test_non_dict_rows_ignored(self) -> None:
        predicted: dict[str, object] = {
            "query_results": ["string_row", {"FileName": "ok.exe"}]
        }
        patterns = {"FileName": r"ok\.exe"}
        score = score_kql_development(predicted, self._sample(patterns))
        # One valid row, one non-dict, precision = 1/2 but recall = 1.0
        assert score > 0.0

    def test_patterns_at_top_level(self) -> None:
        """Patterns can live at sample_data top level (no ground_truth nesting)."""
        predicted: dict[str, object] = {
            "query_results": [{"Process": "cmd.exe"}]
        }
        sample: dict[str, object] = {"regex_patterns": {"Process": r"cmd\.exe"}}
        score = score_kql_development(predicted, sample)
        assert score > 0.0

    def test_score_capped_at_one(self) -> None:
        predicted: dict[str, object] = {
            "query_results": [
                {"F": "v"} for _ in range(10)  # many perfect rows
            ]
        }
        patterns = {"F": r"v"}
        score = score_kql_development(predicted, self._sample(patterns))
        assert score <= 1.0

    def test_case_insensitive_field_matching(self) -> None:
        """Pattern key 'FileName' should match row key 'filename'."""
        predicted: dict[str, object] = {
            "query_results": [{"filename": "malware.exe"}]
        }
        patterns = {"FileName": r"malware\.exe"}
        score = score_kql_development(predicted, self._sample(patterns))
        assert score > 0.0

    def test_invalid_regex_pattern_raises(self) -> None:
        """Invalid regex in ground-truth pattern is a config bug — must raise."""
        predicted: dict[str, object] = {
            "query_results": [{"field": "value"}]
        }
        patterns = {"field": r"[invalid(regex"}
        with pytest.raises(re.error):
            score_kql_development(predicted, self._sample(patterns))

    def test_DEVICENAME_uppercase_field(self) -> None:
        """DEVICENAME (all caps) should be recognized for linux validation."""
        expected_host = "arjunc-cti-vm-3.wqgilo2whriehm0ezwjionoa3a.xx.internal.cloudapp.net"
        predicted: dict[str, object] = {
            "query_results": [{"DEVICENAME": expected_host, "F": "v"}]
        }
        patterns = {"F": r"v"}
        score = score_kql_development(predicted, self._sample(patterns), sample_id="linux_test")
        assert score > 0.0
