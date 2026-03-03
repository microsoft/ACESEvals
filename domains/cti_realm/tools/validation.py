"""Output validation tool for the CTI Realm sandbox."""

from __future__ import annotations

import json

from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox


@tool
def validate_output_json(timeout: int = 120) -> Tool:
    """Validate your final output JSON before submitting.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(json_data: str) -> str:
        """Validate the output JSON has all required fields.

        Args:
            json_data: Your complete JSON output string to validate.
        """
        script = f"""\
import json

json_str = {json.dumps(json_data)}

try:
    data = json.loads(json_str)

    if not isinstance(data, dict):
        print(json.dumps({{"valid": False, "error": "Output must be a JSON object (dictionary)"}}))
    else:
        required_keys = {{"sigma_rule", "kql_query", "query_results"}}
        missing = required_keys - set(data.keys())
        extra = set(data.keys()) - required_keys

        if missing:
            print(json.dumps({{"valid": False, "error": f"Missing required keys: {{list(missing)}}"}}))
        elif extra:
            print(json.dumps({{"valid": False, "error": f"Unexpected extra keys: {{list(extra)}}"}}))
        elif not isinstance(data.get("sigma_rule"), str):
            print(json.dumps({{"valid": False, "error": "sigma_rule must be a string"}}))
        elif len(data["sigma_rule"]) < 50:
            print(json.dumps({{"valid": False, "error": "sigma_rule too short (min 50 chars)"}}))
        elif not isinstance(data.get("kql_query"), str):
            print(json.dumps({{"valid": False, "error": "kql_query must be a string"}}))
        elif len(data["kql_query"]) < 10:
            print(json.dumps({{"valid": False, "error": "kql_query too short (min 10 chars)"}}))
        elif not isinstance(data.get("query_results"), list):
            print(json.dumps({{"valid": False, "error": "query_results must be a list"}}))
        elif len(data["query_results"]) == 0:
            print(json.dumps({{"valid": False, "error": "query_results cannot be empty"}}))
        else:
            print(json.dumps({{"valid": True, "message": "Output JSON is valid and contains all required fields"}}))
except json.JSONDecodeError as e:
    print(json.dumps({{"valid": False, "error": "Invalid JSON: " + str(e)}}))
except Exception as e:
    print(json.dumps({{"valid": False, "error": "Validation error: " + str(e)}}))
"""
        result = await sandbox().exec(["python3"], input=script, timeout=timeout)
        if result.returncode != 0:
            return f"ERROR: {result.stderr}"
        return result.stdout

    return execute
