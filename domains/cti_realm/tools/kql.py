"""Kusto/KQL query tools for the CTI Realm sandbox."""

from __future__ import annotations

import json

from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox

_KUSTO_BASE = "http://saber-cti-kusto-emulator:8080"
KUSTO_DB = "NetDefaultDB"


async def _kusto_query(csl: str, timeout: int, *, endpoint: str = "query") -> str:
    """Execute a Kusto query via curl in the sandbox.

    Args:
        csl: Kusto query language statement.
        timeout: Command timeout in seconds.
        endpoint: REST endpoint – ``"query"`` (default) or ``"mgmt"``.

    Returns:
        Query result JSON or error string.
    """
    url = f"{_KUSTO_BASE}/v1/rest/{endpoint}"
    payload = json.dumps({"db": KUSTO_DB, "csl": csl})
    result = await sandbox().exec(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
            "-d",
            payload,
        ],
        timeout=timeout,
    )
    if result.returncode != 0:
        return f"ERROR: {result.stderr}"
    return result.stdout


@tool
def execute_kql_query(timeout: int = 120) -> Tool:
    """Execute a KQL query against the Kusto database.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(query: str, limit: int = 10) -> str:
        """Execute a KQL query and return results.

        Args:
            query: KQL query to execute.
            limit: Maximum rows to return (default: 10, max 10).
        """
        capped_limit = min(limit, 10)
        query_limited = query
        if "| take" not in query and "| limit" not in query:
            query_limited = f"{query} | take {capped_limit}"
        return await _kusto_query(query_limited, timeout)

    return execute


@tool
def list_kusto_tables(timeout: int = 120) -> Tool:
    """List all available tables in the Kusto database.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute() -> str:
        """List all available Kusto database tables."""
        return await _kusto_query(".show tables", timeout, endpoint="mgmt")

    return execute


@tool
def get_table_schema(timeout: int = 120) -> Tool:
    """Get the schema (columns and data types) for a specific table.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(table_name: str) -> str:
        """Get the schema for a Kusto table.

        Args:
            table_name: Name of the table to examine.
        """
        return await _kusto_query(f"{table_name} | getschema", timeout)

    return execute


@tool
def sample_table_data(timeout: int = 120) -> Tool:
    """Get sample rows from a table to understand the data structure.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(table_name: str, limit: int = 5) -> str:
        """Get sample rows from a Kusto table.

        Args:
            table_name: Name of the table to sample.
            limit: Number of rows to return (default: 5, max: 20).
        """
        capped_limit = min(max(1, limit), 20)
        return await _kusto_query(f"{table_name} | take {capped_limit}", timeout)

    return execute
