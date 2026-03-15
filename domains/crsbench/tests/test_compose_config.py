"""Tests for CRSBench default compose configuration.

Validates that the compose YAML contains the correct environment variables
and resource limits for reproducible benchmark builds.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_COMPOSE_PATH = (
    Path(__file__).resolve().parents[1] / "compose" / "default.compose.yml"
)


def _load_default_service_config() -> dict[str, object]:
    """Load and return the 'default' service config from compose YAML."""
    with open(_COMPOSE_PATH) as f:
        data = yaml.safe_load(f)
    return data["services"]["default"]  # type: ignore[no-any-return]


class TestComposeEnvironment:
    """Verify environment variables in default.compose.yml."""

    def test_ldflags_includes_lstdcpp(self) -> None:
        svc = _load_default_service_config()
        env: list[str] = svc["environment"]  # type: ignore[assignment]
        ldflags = [e for e in env if e.startswith("LDFLAGS=")]
        assert ldflags, "LDFLAGS not found in environment"
        assert "-lstdc++" in ldflags[0]

    def test_cflags_suppresses_implicit_function_declaration(self) -> None:
        svc = _load_default_service_config()
        env: list[str] = svc["environment"]  # type: ignore[assignment]
        cflags = [e for e in env if e.startswith("CFLAGS=")]
        assert cflags, "CFLAGS not found in environment"
        assert "-Wno-error=implicit-function-declaration" in cflags[0]

    def test_cxxflags_suppresses_implicit_function_declaration(self) -> None:
        svc = _load_default_service_config()
        env: list[str] = svc["environment"]  # type: ignore[assignment]
        cxxflags = [e for e in env if e.startswith("CXXFLAGS=")]
        assert cxxflags, "CXXFLAGS not found in environment"
        assert "-Wno-error=implicit-function-declaration" in cxxflags[0]


class TestComposeResourceLimits:
    """Verify resource limits in default.compose.yml."""

    def test_memory_limit_is_16g(self) -> None:
        svc = _load_default_service_config()
        memory = svc["deploy"]["resources"]["limits"]["memory"]  # type: ignore[index]
        assert memory == "16G"
