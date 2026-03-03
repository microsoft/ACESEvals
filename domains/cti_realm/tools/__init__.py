"""CTI Realm domain tools for sandbox execution.

Each module provides one or more @tool-decorated functions grouped by concern:

- ``kql``   — Kusto/KQL query execution and table inspection
- ``sigma`` — Sigma detection rule search
- ``mitre`` — MITRE ATT&CK technique lookup
- ``cti``   — CTI threat intelligence report access
- ``validation`` — Output JSON validation
"""

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
    "list_cti_report_tags",
    "list_kusto_tables",
    "sample_table_data",
    "search_mitre_techniques",
    "search_sigma_rules",
    "validate_output_json",
]
