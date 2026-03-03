"""Sigma detection rule search tool for the CTI Realm sandbox."""

from __future__ import annotations

import json

from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox


@tool
def search_sigma_rules(timeout: int = 120) -> Tool:
    """Search Sigma detection rules by keyword, technique ID, or platform.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(
        keyword: str = "",
        technique_id: str = "",
        platform: str = "",
        limit: int = 5,
    ) -> str:
        """Search Sigma detection rules.

        Args:
            keyword: Search keyword to match in rule title or description.
            technique_id: MITRE technique ID to filter by.
            platform: Platform filter.
            limit: Maximum number of results to return.
        """
        script = f"""\
import json
from pathlib import Path

keyword = {json.dumps(keyword.lower())}
technique = {json.dumps(technique_id.upper())}
plat = {json.dumps(platform.lower())}
max_results = {limit}

sigma_file = Path("/opt/cti_realm/data/sigma_rules.json")
if not sigma_file.exists():
    print(json.dumps({{"error": "Sigma rules index not found"}}))
else:
    with open(sigma_file) as f:
        rules = json.load(f)
    results = []
    for rule in rules:
        if keyword and keyword not in rule["title"].lower() and keyword not in rule["description"].lower():
            continue
        if technique and technique not in rule["techniques"]:
            continue
        if plat and plat not in rule["platform"].lower():
            continue
        results.append(rule)
        if len(results) >= max_results:
            break
    print(json.dumps({{"count": len(results), "rules": results}}))
"""
        result = await sandbox().exec(["python3"], input=script, timeout=timeout)
        if result.returncode != 0:
            return f"ERROR: {result.stderr}"
        return result.stdout

    return execute
