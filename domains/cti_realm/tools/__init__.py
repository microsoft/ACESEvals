"""CTI Realm domain tools for sandbox execution.

Each module provides one or more @tool-decorated functions grouped by concern:

- ``kql``   — Kusto/KQL query execution and table inspection
- ``sigma`` — Sigma detection rule search
- ``mitre`` — MITRE ATT&CK technique lookup
- ``cti``   — CTI threat intelligence report access
- ``validation`` — Output JSON validation
"""

from collections.abc import Callable
from pathlib import Path

from inspect_ai.tool import Tool

from .cti import get_cti_reports_by_tag, list_cti_report_tags
from .kql import (
    execute_kql_query,
    get_table_schema,
    list_kusto_tables,
    sample_table_data,
)
from .mitre import search_mitre_techniques
from .sigma import search_sigma_rules
from .validation import validate_output_json

__all__ = [
    "execute_kql_query",
    "get_cti_reports_by_tag",
    "get_table_schema",
    "get_tools",
    "list_cti_report_tags",
    "list_kusto_tables",
    "sample_table_data",
    "search_mitre_techniques",
    "search_sigma_rules",
    "validate_output_json",
]


def get_tools(
    domain_root: Path,  # noqa: ARG001
) -> dict[str, Callable[..., Tool]]:
    """Return CTI Realm domain tools for registration.

    Auto-discovered by ``create_task`` when a ``tools/`` package is
    present in the domain directory.

    Args:
        domain_root: Path to the domain root directory.

    Returns:
        Mapping of tool name to tool factory callable.
    """
    return {
        "execute_kql_query": execute_kql_query,
        "get_cti_reports_by_tag": get_cti_reports_by_tag,
        "get_table_schema": get_table_schema,
        "list_cti_report_tags": list_cti_report_tags,
        "list_kusto_tables": list_kusto_tables,
        "sample_table_data": sample_table_data,
        "search_mitre_techniques": search_mitre_techniques,
        "search_sigma_rules": search_sigma_rules,
        "validate_output_json": validate_output_json,
    }
