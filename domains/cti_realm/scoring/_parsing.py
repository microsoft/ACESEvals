"""Pure parsing utilities for CTI Realm model outputs.

Ported from server/scoring/parsing_utils.py — no SABER server dependencies.
"""

import json
import re

from saber.logging import get_logger

logger = get_logger("domains.cti_realm.scoring.parsing")


def extract_fields_with_regex(output: str) -> dict[str, object]:
    """Extract sigma_rule, kql_query, and query_results via regex fallback.

    Args:
        output: Raw text output from model.

    Returns:
        Dictionary with extracted fields.
    """
    result: dict[str, object] = {}

    # --- sigma_rule ---
    sigma_patterns = [
        r'"sigma_rule"\s*:\s*"((?:[^"\\]|\\.)*)"',
        r"'sigma_rule'\s*:\s*'((?:[^'\\]|\\.)*)'",
        r'"sigma_rule"\s*:\s*\'((?:[^\'\\]|\\.)*)\'',
    ]
    for pattern in sigma_patterns:
        match = re.search(pattern, output, re.DOTALL)
        if match:
            sigma_rule = match.group(1)
            sigma_rule = (
                sigma_rule.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\'", "'")
            )
            result["sigma_rule"] = sigma_rule
            break

    # --- kql_query ---
    kql_patterns = [
        r'"kql_query"\s*:\s*"((?:[^"\\]|\\.)*)"',
        r"'kql_query'\s*:\s*'((?:[^'\\]|\\.)*)'",
        r'"kql_query"\s*:\s*\'((?:[^\'\\]|\\.)*)\'',
    ]
    for pattern in kql_patterns:
        match = re.search(pattern, output, re.DOTALL)
        if match:
            kql_query = match.group(1)
            kql_query = (
                kql_query.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\'", "'")
            )
            result["kql_query"] = kql_query
            break

    # --- query_results ---
    results_patterns = [
        r'"query_results"\s*:\s*(\[.*?\](?=\s*[,}]|\s*$))',
        r"'query_results'\s*:\s*(\[.*?\](?=\s*[,}]|\s*$))",
    ]
    for pattern in results_patterns:
        match = re.search(pattern, output, re.DOTALL)
        if match:
            try:
                result["query_results"] = json.loads(match.group(1))
                break
            except json.JSONDecodeError:
                continue

    if "query_results" not in result:
        match = re.search(
            r'"query_results"\s*:\s*\[(.*?)\](?=\s*[,}]|\s*$)', output, re.DOTALL
        )
        if not match:
            match = re.search(
                r"'query_results'\s*:\s*\[(.*?)\](?=\s*[,}]|\s*$)", output, re.DOTALL
            )
        if match:
            try:
                content = match.group(1).strip()
                result["query_results"] = json.loads(f"[{content}]") if content else []
            except json.JSONDecodeError:
                pass

    return result


def parse_model_output(output: str) -> dict[str, object]:
    """Parse model JSON output with regex fallback.

    Args:
        output: Raw output string from the model.

    Returns:
        Dictionary with parsed fields.
    """
    json_cleaned = re.sub(
        r"^```json\s*|\s*```$", "", output.strip(), flags=re.MULTILINE
    )
    try:
        parsed = json.loads(json_cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return extract_fields_with_regex(output)


def extract_sigma_scores_from_text(text: str) -> tuple[float, float]:
    """Extract syntax and specificity scores from text.

    Args:
        text: Raw text from LLM judge.

    Returns:
        Tuple of (syntax_score, specificity_score), each 0.0–1.0.
    """
    syntax_score = 0.05
    specificity_score = 0.05

    for pat in [
        r'"syntax_score"\s*:\s*([0-9]*\.?[0-9]+)',
        r"syntax_score\s*:\s*([0-9]*\.?[0-9]+)",
        r"syntax\s*:\s*([0-9]*\.?[0-9]+)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 0.0 <= val <= 1.0:
                syntax_score = val
                break

    for pat in [
        r'"specificity"\s*:\s*([0-9]*\.?[0-9]+)',
        r"specificity\s*:\s*([0-9]*\.?[0-9]+)",
        r"specificity_score\s*:\s*([0-9]*\.?[0-9]+)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 0.0 <= val <= 1.0:
                specificity_score = val
                break

    return syntax_score, specificity_score
