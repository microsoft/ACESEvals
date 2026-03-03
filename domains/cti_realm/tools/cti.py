"""CTI threat intelligence report tools for the CTI Realm sandbox."""

from __future__ import annotations

import json

from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox


@tool
def list_cti_report_tags(timeout: int = 120) -> Tool:
    """List all available CTI report tags to discover threat intelligence topics.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute() -> str:
        """List all available CTI report tags."""
        script = """\
import json
from pathlib import Path
from collections import Counter

reports_file = Path("/opt/cti_realm/data/cti_reports/reports.jsonl")
tag_counter = Counter()

if reports_file.exists():
    with open(reports_file) as f:
        for line in f:
            if line.strip():
                report = json.loads(line)
                tag_counter.update(report.get("tags", []))

sorted_tags = sorted(tag_counter.items(), key=lambda x: x[1], reverse=True)
print(json.dumps({
    "available_tags": [tag for tag, _ in sorted_tags],
    "tag_counts": dict(sorted_tags),
}))
"""
        result = await sandbox().exec(["python3"], input=script, timeout=timeout)
        if result.returncode != 0:
            return f"ERROR: {result.stderr}"
        return result.stdout

    return execute


@tool
def get_cti_reports_by_tag(timeout: int = 120) -> Tool:
    """Get CTI threat intelligence reports for a specific tag.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(tag: str) -> str:
        """Get CTI reports filtered by tag.

        Args:
            tag: The tag to filter by (e.g., 'apt', 'persistence', 'linux').
        """
        script = f"""\
import json
from pathlib import Path

tag = {json.dumps(tag)}.lower()
reports_file = Path("/opt/cti_realm/data/cti_reports/reports.jsonl")
matching_reports = []
all_tags = set()

if reports_file.exists():
    with open(reports_file) as f:
        for line in f:
            if line.strip():
                report = json.loads(line)
                report_tags = report.get("tags", [])
                all_tags.update(report_tags)
                if tag in [t.lower() for t in report_tags]:
                    matching_reports.append(report)

if matching_reports:
    print(json.dumps({{"count": len(matching_reports), "reports": matching_reports}}))
else:
    print(json.dumps({{"error": f"No reports found for tag '{{tag}}'", "available_tags": sorted(list(all_tags))}}))
"""
        result = await sandbox().exec(["python3"], input=script, timeout=timeout)
        if result.returncode != 0:
            return f"ERROR: {result.stderr}"
        return result.stdout

    return execute
