"""KQL development scoring — pure F1 with quality bonuses.

Ported from server/scoring/scorer.py (_score_kql_development).
No SABER server dependencies.
"""

import json
import logging
import re

logger = logging.getLogger("saber.domains.cti_realm.scoring.kql")


def _validate_linux_device_name(
    results: list[dict[str, object]], sample_id: str
) -> bool:
    """Return False if a linux_ sample lacks the expected DeviceName.

    Ground-truth value from CTI Realm benchmark dataset.
    """
    if not sample_id.startswith("linux_"):
        return True
    # Ground-truth value from CTI Realm benchmark dataset
    expected = "arjunc-cti-vm-3.wqgilo2whriehm0ezwjionoa3a.xx.internal.cloudapp.net"
    for row in results:
        if isinstance(row, dict):
            name = (
                row.get("DeviceName")
                or row.get("devicename")
                or row.get("DEVICENAME")
            )
            if name == expected:
                return True
    logger.warning("[%s] LINUX CHECK FAILED: missing DeviceName '%s'", sample_id, expected)
    return False


def _validate_aks_time_generated(
    results: list[dict[str, object]], sample_id: str
) -> bool:
    """Return False if an aks_ sample lacks the expected TimeGenerated date.

    Ground-truth value from CTI Realm benchmark dataset.
    """
    if not sample_id.startswith("aks_"):
        return True
    # Ground-truth value from CTI Realm benchmark dataset
    expected_date = "2025-10-31"
    for row in results:
        if isinstance(row, dict):
            tg = (
                row.get("TimeGenerated")
                or row.get("timegenerated")
                or row.get("TIMEGENERATED")
            )
            if tg and str(tg).split("T")[0] == expected_date:
                return True
    logger.warning(
        "[%s] AKS CHECK FAILED: missing TimeGenerated '%s'", sample_id, expected_date
    )
    return False


def score_kql_development(
    predicted: dict[str, object],
    sample_data: dict[str, object],
    sample_id: str = "unknown",
) -> float:
    """Score KQL query results using precision-focused F1 with quality bonuses.

    Args:
        predicted: Parsed model output containing ``query_results``.
        sample_data: Ground-truth data with ``regex_patterns`` (possibly nested
            under ``ground_truth``).
        sample_id: Sample identifier for validation checks.

    Returns:
        Float score in [0, 1].
    """
    if "query_results" not in predicted:
        return 0.0

    # Extract regex patterns
    gt = sample_data.get("ground_truth")
    if isinstance(gt, dict):
        patterns: dict[str, str] = gt.get("regex_patterns", {})  # type: ignore[assignment]
    else:
        patterns = sample_data.get("regex_patterns", {})  # type: ignore[assignment]

    if not patterns:
        return 0.0

    # Parse results
    results = predicted["query_results"]
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except json.JSONDecodeError:
            return 0.0

    if not isinstance(results, list) or not results:
        return 0.0

    if not _validate_linux_device_name(results, sample_id):
        return 0.0
    if not _validate_aks_time_generated(results, sample_id):
        return 0.0

    # --- row-level matching ---
    def _row_match_count(row: dict[str, object]) -> int:
        count = 0
        for field, pattern in patterns.items():
            for rf, rv in row.items():
                if rf.lower() == field.lower():
                    if re.search(pattern, str(rv)):
                        count += 1
                    break
        return count

    relevant_rows: list[int] = []
    perfect_rows: list[int] = []
    fields_found: set[str] = set()

    for i, row in enumerate(results):
        if not isinstance(row, dict):
            continue
        mc = _row_match_count(row)
        if mc == len(patterns):
            perfect_rows.append(i)
            relevant_rows.append(i)
        elif mc > 0:
            relevant_rows.append(i)

        # track fields
        for field, pattern in patterns.items():
            for rf, rv in row.items():
                if rf.lower() == field.lower():
                    if re.search(pattern, str(rv)):
                        fields_found.add(field)
                    break

    precision = len(relevant_rows) / len(results) if results else 0.0
    recall = len(fields_found) / len(patterns) if patterns else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    quality_bonus = min(0.2, 0.05 * len(perfect_rows))
    return min(1.0, f1 * (1.0 + quality_bonus))
