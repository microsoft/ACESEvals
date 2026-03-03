"""Tests for cti_realm/tools.py — tool function signatures and structure."""

from __future__ import annotations

import inspect

from cti_realm.tools import (
    execute_kql_query,
    get_cti_reports_by_tag,
    get_table_schema,
    list_cti_report_tags,
    list_kusto_tables,
    sample_table_data,
    search_mitre_techniques,
    search_sigma_rules,
    validate_output_json,
)


class TestToolDecorators:
    """Verify each @tool factory returns a callable with correct structure."""

    def test_execute_kql_query_returns_callable(self) -> None:
        inner = execute_kql_query()
        assert callable(inner)

    def test_search_sigma_rules_returns_callable(self) -> None:
        inner = search_sigma_rules()
        assert callable(inner)

    def test_search_mitre_techniques_returns_callable(self) -> None:
        inner = search_mitre_techniques()
        assert callable(inner)

    def test_list_kusto_tables_returns_callable(self) -> None:
        inner = list_kusto_tables()
        assert callable(inner)

    def test_get_table_schema_returns_callable(self) -> None:
        inner = get_table_schema()
        assert callable(inner)

    def test_sample_table_data_returns_callable(self) -> None:
        inner = sample_table_data()
        assert callable(inner)

    def test_list_cti_report_tags_returns_callable(self) -> None:
        inner = list_cti_report_tags()
        assert callable(inner)

    def test_get_cti_reports_by_tag_returns_callable(self) -> None:
        inner = get_cti_reports_by_tag()
        assert callable(inner)

    def test_validate_output_json_returns_callable(self) -> None:
        inner = validate_output_json()
        assert callable(inner)


class TestToolSignatures:
    """Verify inner function signatures have expected parameters."""

    def test_execute_kql_query_params(self) -> None:
        inner = execute_kql_query()
        sig = inspect.signature(inner)
        assert "query" in sig.parameters
        assert "limit" in sig.parameters

    def test_search_sigma_rules_params(self) -> None:
        inner = search_sigma_rules()
        sig = inspect.signature(inner)
        params = set(sig.parameters.keys())
        assert {"keyword", "technique_id", "platform", "limit"} <= params

    def test_search_mitre_techniques_params(self) -> None:
        inner = search_mitre_techniques()
        sig = inspect.signature(inner)
        assert "tactic" in sig.parameters

    def test_list_kusto_tables_no_required_params(self) -> None:
        inner = list_kusto_tables()
        sig = inspect.signature(inner)
        # All params should have defaults (no required params)
        for param in sig.parameters.values():
            assert param.default is not inspect.Parameter.empty or param.name == "self"

    def test_get_table_schema_params(self) -> None:
        inner = get_table_schema()
        sig = inspect.signature(inner)
        assert "table_name" in sig.parameters

    def test_sample_table_data_params(self) -> None:
        inner = sample_table_data()
        sig = inspect.signature(inner)
        assert "table_name" in sig.parameters
        assert "limit" in sig.parameters

    def test_get_cti_reports_by_tag_params(self) -> None:
        inner = get_cti_reports_by_tag()
        sig = inspect.signature(inner)
        assert "tag" in sig.parameters

    def test_validate_output_json_params(self) -> None:
        inner = validate_output_json()
        sig = inspect.signature(inner)
        assert "json_data" in sig.parameters


class TestToolFactoryTimeout:
    """Verify timeout parameter on outer factory functions."""

    def test_execute_kql_query_custom_timeout(self) -> None:
        inner = execute_kql_query(timeout=60)
        assert callable(inner)

    def test_search_sigma_rules_custom_timeout(self) -> None:
        inner = search_sigma_rules(timeout=30)
        assert callable(inner)

    def test_validate_output_json_custom_timeout(self) -> None:
        inner = validate_output_json(timeout=10)
        assert callable(inner)


class TestToolInnerFunctionsAreAsync:
    """All inner tool functions should be coroutines."""

    def test_execute_kql_query_is_async(self) -> None:
        inner = execute_kql_query()
        assert inspect.iscoroutinefunction(inner)

    def test_search_sigma_rules_is_async(self) -> None:
        inner = search_sigma_rules()
        assert inspect.iscoroutinefunction(inner)

    def test_list_kusto_tables_is_async(self) -> None:
        inner = list_kusto_tables()
        assert inspect.iscoroutinefunction(inner)

    def test_get_cti_reports_by_tag_is_async(self) -> None:
        inner = get_cti_reports_by_tag()
        assert inspect.iscoroutinefunction(inner)

    def test_validate_output_json_is_async(self) -> None:
        inner = validate_output_json()
        assert inspect.iscoroutinefunction(inner)
