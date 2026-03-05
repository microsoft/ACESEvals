"""Shared fixtures and sys.path setup for CRSBench tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Add domains/ to sys.path so "crsbench" is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
