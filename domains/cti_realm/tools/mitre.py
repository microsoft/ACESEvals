"""MITRE ATT&CK technique search tool for the CTI Realm sandbox."""

from __future__ import annotations

import json

from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox


@tool
def search_mitre_techniques(timeout: int = 120) -> Tool:
    """Search MITRE ATT&CK techniques by tactic.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(tactic: str = "") -> str:
        """Search MITRE ATT&CK techniques by tactic name.

        Args:
            tactic: MITRE tactic name (e.g., 'initial-access', 'persistence').
        """
        tactic_normalized = tactic.lower().replace(" ", "-")
        script = f"""\
import json
import urllib.request

tactic = {json.dumps(tactic_normalized)}
url = f"http://saber-cti-mitre-service:8081/tactic/{{tactic}}"

try:
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read().decode()
        print(data)
except Exception as e:
    print(json.dumps({{"error": f"Failed to query MITRE service: {{str(e)}}"}}))
"""
        result = await sandbox().exec(["python3"], input=script, timeout=timeout)
        if result.returncode != 0:
            return f"ERROR: {result.stderr}"
        return result.stdout

    return execute
