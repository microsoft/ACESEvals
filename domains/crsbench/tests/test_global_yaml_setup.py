"""Tests for the git-init commands in the L2 overlay Dockerfile.

After the refactor, git init is baked into the Docker image at build time
(via ``generate_overlay_dockerfile``) rather than running per-sample at
container startup.  These tests verify the Dockerfile contains the
expected git-init commands.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from crsbench.scripts.build_images import generate_overlay_dockerfile

_GLOBAL_YAML = Path(__file__).resolve().parents[1] / "tasks" / "global.yaml"


def _overlay() -> str:
    """Return the generated L2 overlay Dockerfile content."""
    return generate_overlay_dockerfile("test-env:latest")


class TestGlobalYamlNoSetup:
    """Verify that ``global.yaml`` no longer has a ``setup`` field."""

    def test_setup_field_absent(self) -> None:
        with open(_GLOBAL_YAML) as f:
            data = yaml.safe_load(f)
        assert "setup" not in data.get("global_defaults", {})


class TestDockerfileGitInit:
    """Validate the git-init RUN layer in the L2 overlay Dockerfile."""

    def test_removes_nested_git_dirs(self) -> None:
        assert "find . -mindepth 2 -name .git" in _overlay()

    def test_creates_gitignore(self) -> None:
        assert ".gitignore" in _overlay()

    def test_gitignore_contains_build_artifact_patterns(self) -> None:
        df = _overlay()
        for pattern in ("*.o", "*.a", "*.so", "*.class", "*.jar", "*.pyc"):
            assert pattern in df, f"Missing gitignore pattern: {pattern}"

    def test_git_init_present(self) -> None:
        assert "git init" in _overlay()

    def test_git_config_user(self) -> None:
        df = _overlay()
        assert "sandbox@saber" in df
        assert "sandbox" in df

    def test_git_add_and_commit(self) -> None:
        df = _overlay()
        assert "git add -A" in df
        assert "git commit" in df

    def test_allow_empty_commit(self) -> None:
        assert "--allow-empty" in _overlay()

    def test_git_init_runs_after_build_sh(self) -> None:
        df = _overlay()
        build_pos = df.index("bash build.sh")
        git_pos = df.index("git init")
        assert git_pos > build_pos

    def test_no_vulnerability_info(self) -> None:
        """Git-init RUN commands must not leak any fix / patch / CVE info."""
        df = _overlay()
        git_section = df[df.index("Git init"):]
        # Only check actual RUN lines, not Dockerfile comments
        run_lines = [
            line for line in git_section.splitlines()
            if not line.lstrip().startswith("#")
        ]
        lowered = "\n".join(run_lines).lower()
        for keyword in ("cve-", "vuln", "exploit"):
            assert keyword not in lowered, (
                f"Git-init commands should not contain '{keyword}'"
            )
