"""Pydantic models for CRSBench meta.yaml parsing.

These models represent the `.aixcc/meta.yaml` structure found in each
CRSBench benchmark directory. Used by the task generation scripts only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CRSBenchPOV(BaseModel):
    """A single proof-of-vulnerability entry."""

    model_config = ConfigDict(frozen=True)

    id: str
    sanitizer: str
    error_token: str


class CRSBenchVuln(BaseModel):
    """A single vulnerability entry in meta.yaml."""

    model_config = ConfigDict(frozen=True)

    vuln_keyword: str
    povs: tuple[CRSBenchPOV, ...]
    patch_superset: str | None = None
    difficulty_level: int | None = None


class CRSBenchHarness(BaseModel):
    """A fuzz harness entry in meta.yaml."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    vulns: tuple[CRSBenchVuln, ...] = ()


class CRSBenchDeltaMode(BaseModel):
    """Delta-mode commit configuration."""

    model_config = ConfigDict(frozen=True)

    base_commit: str
    ref_commit: str


class CRSBenchFullMode(BaseModel):
    """Full-mode commit configuration."""

    model_config = ConfigDict(frozen=True)

    base_commit: str


class CRSBenchMeta(BaseModel):
    """Parsed .aixcc/meta.yaml for a benchmark.

    Attributes:
        patch_exclude_list: Glob patterns for files that must not be patched.
        delta_mode: Delta-mode commit references (base + ref).
        full_mode: Full-mode commit reference (base only).
        harness_files: Fuzz harness configurations with vulnerabilities.
    """

    model_config = ConfigDict(frozen=True)

    patch_exclude_list: tuple[str, ...]
    delta_mode: CRSBenchDeltaMode | None = None
    full_mode: CRSBenchFullMode | None = None
    harness_files: tuple[CRSBenchHarness, ...]
