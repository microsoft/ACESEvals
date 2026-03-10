"""Shared fixtures and sys.path setup for CRSBench tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add domains/ to sys.path so "crsbench" is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (require Docker + data)",
    )
