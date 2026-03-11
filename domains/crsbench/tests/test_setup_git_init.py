"""Tests for CRSBench git-init sandbox setup.

Verifies that:
- The ``_GIT_INIT_SETUP`` constant contains required git commands.
- The ``crsbench()`` task function injects ``setup`` into every sample.
- The setup script contains no vulnerability fix information.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from inspect_ai import Task
from inspect_ai.dataset import MemoryDataset, Sample

from crsbench.crsbench import _GIT_INIT_SETUP, crsbench


# ---------------------------------------------------------------------------
# _GIT_INIT_SETUP constant tests
# ---------------------------------------------------------------------------


class TestGitInitSetupConstant:
    """Validate the git-init setup script constant."""

    def test_starts_with_shebang(self) -> None:
        assert _GIT_INIT_SETUP.startswith("#!/usr/bin/env bash\n")

    def test_uses_strict_mode(self) -> None:
        assert "set -euo pipefail" in _GIT_INIT_SETUP

    def test_changes_to_workspace_source(self) -> None:
        assert "cd /workspace/source" in _GIT_INIT_SETUP

    def test_removes_nested_git_dirs(self) -> None:
        """Nested .git dirs must be removed to avoid submodule treatment."""
        assert "find . -mindepth 2 -name .git" in _GIT_INIT_SETUP

    def test_gitignore_for_build_artifacts(self) -> None:
        """A .gitignore must suppress build artifacts from git diff."""
        assert "*.o" in _GIT_INIT_SETUP
        assert ".gitignore" in _GIT_INIT_SETUP

    def test_initialises_git_repo(self) -> None:
        assert "git init" in _GIT_INIT_SETUP

    def test_configures_user_email(self) -> None:
        assert "git config user.email" in _GIT_INIT_SETUP

    def test_configures_user_name(self) -> None:
        assert "git config user.name" in _GIT_INIT_SETUP

    def test_stages_all_files(self) -> None:
        assert "git add -A" in _GIT_INIT_SETUP

    def test_creates_initial_commit(self) -> None:
        assert "git commit" in _GIT_INIT_SETUP

    def test_no_vulnerability_info(self) -> None:
        """Setup must not leak any fix / patch / CVE information."""
        lowered = _GIT_INIT_SETUP.lower()
        for keyword in ("cve-", "fix", "vuln", "patch", "exploit"):
            assert keyword not in lowered, (
                f"Setup script should not contain '{keyword}'"
            )


# ---------------------------------------------------------------------------
# Sample injection tests
# ---------------------------------------------------------------------------


class TestSampleInjection:
    """Verify that crsbench() injects _GIT_INIT_SETUP into every sample."""

    @staticmethod
    def _make_task(samples: list[Sample]) -> Task:
        """Build a minimal Task wrapping the given samples."""
        return Task(dataset=MemoryDataset(samples))

    def test_injects_setup_into_all_samples(self) -> None:
        samples = [
            Sample(input="q1"),
            Sample(input="q2"),
            Sample(input="q3"),
        ]
        fake_task = self._make_task(samples)

        with patch("crsbench.crsbench.create_task", return_value=fake_task):
            result = crsbench()

        for sample in result.dataset:
            assert sample.setup == _GIT_INIT_SETUP

    def test_overwrites_existing_setup(self) -> None:
        samples = [Sample(input="q1", setup="old script")]
        fake_task = self._make_task(samples)

        with patch("crsbench.crsbench.create_task", return_value=fake_task):
            result = crsbench()

        assert list(result.dataset)[0].setup == _GIT_INIT_SETUP

    def test_preserves_sample_count(self) -> None:
        samples = [Sample(input=f"q{i}") for i in range(5)]
        fake_task = self._make_task(samples)

        with patch("crsbench.crsbench.create_task", return_value=fake_task):
            result = crsbench()

        assert len(list(result.dataset)) == 5

    def test_forwards_kwargs_to_create_task(self) -> None:
        fake_task = self._make_task([Sample(input="q")])
        with patch(
            "crsbench.crsbench.create_task", return_value=fake_task
        ) as mock_ct:
            crsbench(task_filter="sanity_*", build="true")

        mock_ct.assert_called_once_with(task_filter="sanity_*", build="true")

    def test_handles_empty_dataset(self) -> None:
        """inspect_ai Task rejects empty datasets, so this can't occur."""
        with pytest.raises(ValueError, match="empty"):
            self._make_task([])
