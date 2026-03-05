"""Pydantic models for CRSBench meta.yaml parsing.

These models represent the `.aixcc/meta.yaml` structure found in each
CRSBench benchmark directory. Used by the task generation scripts only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CRSBenchVuln(BaseModel):
    """A single vulnerability entry in meta.yaml."""

    model_config = ConfigDict(frozen=True)

    vuln_keyword: str
    sanitizer: str
    difficulty: int


class CRSBenchHarness(BaseModel):
    """A fuzz harness entry in meta.yaml."""

    model_config = ConfigDict(frozen=True)

    name: str
    source: str
    vulns: tuple[CRSBenchVuln, ...]


class CRSBenchMeta(BaseModel):
    """Parsed .aixcc/meta.yaml for a benchmark.

    Attributes:
        project: Project name (e.g. "sanity-mock-c").
        language: Programming language (e.g. "c", "cpp").
        cp_sources: Source directory paths within the project.
        harnesses: Fuzz harness configurations with vulnerabilities.
    """

    model_config = ConfigDict(frozen=True)

    project: str
    language: str
    cp_sources: tuple[str, ...]
    harnesses: tuple[CRSBenchHarness, ...]
