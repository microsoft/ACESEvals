"""Tests for CRSBench global.yaml configuration.

Verifies that ``global.yaml`` no longer has a ``setup`` field — git init
is now baked into the Docker image at build time via
``generate_overlay_dockerfile``.  The git-init Dockerfile tests live in
``test_build_images.py::TestGitInitResilience``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_GLOBAL_YAML = Path(__file__).resolve().parents[1] / "tasks" / "global.yaml"


class TestGlobalYamlNoSetup:
    """Verify that ``global.yaml`` no longer has a ``setup`` field."""

    def test_setup_field_absent(self) -> None:
        with open(_GLOBAL_YAML) as f:
            data = yaml.safe_load(f)
        assert "setup" not in data.get("global_defaults", {})
