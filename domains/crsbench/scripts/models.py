"""Pydantic models for CRSBench meta.yaml parsing.

These models represent the ``.aixcc/meta.yaml`` structure found in each
CRSBench benchmark directory (from the AIxCC competition format).
Used by the task generation scripts only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CRSBenchPov(BaseModel):
    """A single proof-of-vulnerability entry within a vuln."""

    model_config = ConfigDict(frozen=True)

    id: str
    sanitizer: str
    error_token: str = ""


class CRSBenchPOV(BaseModel):
    """A single proof-of-vulnerability entry."""

    model_config = ConfigDict(frozen=True)

    id: str
    sanitizer: str
    error_token: str


class CRSBenchVuln(BaseModel):
    """A single vulnerability entry within a harness.

    Attributes:
        vuln_keyword: Vulnerability identifier (e.g. ``"cpv_0"``).
        povs: List of proof-of-vulnerability entries with sanitizer info.
    """

    model_config = ConfigDict(frozen=True)

    vuln_keyword: str
    povs: tuple[CRSBenchPOV, ...] = ()
    patch_superset: str | None = None
    difficulty_level: int | None = None

    @property
    def sanitizer(self) -> str:
        """Primary sanitizer from the first POV, or ``"address"``."""
        if self.povs:
            return self.povs[0].sanitizer
        return "address"


class CRSBenchHarness(BaseModel):
    """A fuzz harness entry in meta.yaml.

    Attributes:
        name: Harness name (e.g. ``"curl_fuzzer_ws"``).
        path: Source file path (e.g. ``"$PROJECT/curl_fuzzer/curl_fuzzer.cc"``).
        vulns: Vulnerabilities in this harness (empty if none).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    path: str = ""
    vulns: tuple[CRSBenchVuln, ...] = ()


class CRSBenchDeltaMode(BaseModel):
    """Delta-mode commit configuration."""

    model_config = ConfigDict(frozen=True)

    base_commit: str = ""
    ref_commit: str = ""


class CRSBenchFullMode(BaseModel):
    """Full-mode commit configuration."""

    model_config = ConfigDict(frozen=True)

    base_commit: str = ""


class CRSBenchMeta(BaseModel):
    """Parsed .aixcc/meta.yaml for a benchmark.

    Represents the AIxCC competition meta.yaml format. Only the fields
    relevant for task generation are modeled; extra fields are allowed.

    Attributes:
        patch_exclude_list: Glob patterns for files that must not be patched.
        delta_mode: Delta-mode commit references (base + ref).
        full_mode: Full-mode commit reference (base only).
        harness_files: Fuzz harness configurations with vulnerabilities.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    patch_exclude_list: tuple[str, ...] = ()
    delta_mode: CRSBenchDeltaMode | None = None
    full_mode: CRSBenchFullMode | None = None
    harness_files: tuple[CRSBenchHarness, ...] = ()

    @property
    def harnesses_with_vulns(self) -> list[CRSBenchHarness]:
        """Return only harnesses that have at least one vulnerability."""
        return [h for h in self.harness_files if h.vulns]
