"""Tests for the simplified CRSBench task function.

Verifies that:
- ``crsbench()`` delegates directly to ``create_task()``.
- All kwargs are forwarded without filtering.
- No git-init injection or metadata promotion happens in crsbench.py
  (these are now handled by global.yaml's ``setup`` field and the
  converter's metadata promotion, respectively).
"""

from __future__ import annotations

from unittest.mock import patch

from inspect_ai import Task
from inspect_ai.dataset import MemoryDataset, Sample

_CREATE_TASK_PATCH = "crsbench.crsbench.create_task"


# ---------------------------------------------------------------------------
# Simplified task function tests
# ---------------------------------------------------------------------------


class TestCrsbenchTask:
    """Validate the thin ``crsbench()`` wrapper delegates to ``create_task``."""

    @staticmethod
    def _make_task(samples: list[Sample]) -> Task:
        """Build a minimal Task wrapping the given samples."""
        return Task(dataset=MemoryDataset(samples))

    def test_forwards_all_kwargs(self) -> None:
        """All kwargs should pass through to create_task unchanged."""
        fake_task = self._make_task([Sample(input="q")])
        with patch(_CREATE_TASK_PATCH, return_value=fake_task) as mock_ct:
            from crsbench.crsbench import crsbench

            crsbench(task_filter="sanity_*", dataset="lite", agent="react")

        mock_ct.assert_called_once_with(
            task_filter="sanity_*", dataset="lite", agent="react"
        )

    def test_returns_create_task_result(self) -> None:
        """crsbench() should return exactly what create_task() returns."""
        fake_task = self._make_task([Sample(input="q")])
        with patch(_CREATE_TASK_PATCH, return_value=fake_task):
            from crsbench.crsbench import crsbench

            result = crsbench()

        assert result is fake_task

    def test_no_sample_mutation(self) -> None:
        """crsbench() must not modify samples (setup injection removed)."""
        samples = [Sample(input="q1"), Sample(input="q2")]
        fake_task = self._make_task(samples)
        with patch(_CREATE_TASK_PATCH, return_value=fake_task):
            from crsbench.crsbench import crsbench

            result = crsbench()

        for sample in result.dataset:
            assert sample.setup is None

    def test_no_domain_only_params_constant(self) -> None:
        """_DOMAIN_ONLY_PARAMS should no longer exist in the module."""
        import crsbench.crsbench as mod

        assert not hasattr(mod, "_DOMAIN_ONLY_PARAMS")

    def test_no_git_init_constant(self) -> None:
        """_GIT_INIT_SETUP should no longer exist in the module."""
        import crsbench.crsbench as mod

        assert not hasattr(mod, "_GIT_INIT_SETUP")

    def test_no_lite_task_ids_constant(self) -> None:
        """_LITE_TASK_IDS should no longer exist in the module."""
        import crsbench.crsbench as mod

        assert not hasattr(mod, "_LITE_TASK_IDS")

    def test_no_domain_root_constant(self) -> None:
        """_DOMAIN_ROOT should no longer exist in the module."""
        import crsbench.crsbench as mod

        assert not hasattr(mod, "_DOMAIN_ROOT")
