"""Tests for CRSBench patch verification scoring strategy.

Covers all three score tiers (1.0, 0.5, 0.0) and edge cases (multiple
patches, multiple POVs, missing test script, build failures, etc.).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import Score

from crsbench.scoring.patch_verify import CRSBenchPatchVerifyStrategy
from saber.config.models import DomainCriteria, ScorerConfig
from saber.scoring.context import ScoringContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CRITERIA_EXTRA: dict[str, str] = {
    "source_dir": "/workspace/source",
    "build_script": "",
    "harness_name": "fuzz_target",
    "harness_path": "/workspace/build/fuzz_target",
    "pov_dir": "/workspace/povs",
    "test_script": "/workspace/source/test.sh",
    "patch_dir": "/submit/patches",
}


def _make_exec_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> MagicMock:
    """Build a mock object mimicking sandbox exec() return."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _make_ctx(
    *,
    criteria_extra: dict[str, str] | None = None,
    max_score: float = 1.0,
) -> ScoringContext:
    """Build a minimal ScoringContext for patch verification tests."""
    extra = {**_DEFAULT_CRITERIA_EXTRA, **(criteria_extra or {})}
    criteria = DomainCriteria(**extra)
    scorer = ScorerConfig(
        scorer_name="submission",
        strategy="crsbench_patch_verify",
        criteria=criteria,
        max_score=max_score,
    )
    return ScoringContext(
        submission="",
        tool_steps=(),
        messages=(ChatMessageUser(content="test"),),
        target="",
        task_id="test_task",
        domain="crsbench",
        metadata={},
        scorer=scorer,
    )


def _make_sandbox_mock(exec_side_effects: list[MagicMock]) -> MagicMock:
    """Create a mock sandbox with a sequence of exec() results."""
    sbx = MagicMock()
    sbx.exec = AsyncMock(side_effect=exec_side_effects)
    return sbx


# ---------------------------------------------------------------------------
# Strategy fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy() -> CRSBenchPatchVerifyStrategy:
    return CRSBenchPatchVerifyStrategy()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPatchVerifyScore1_0:
    """Score 1.0: patch builds, fixes all crashes, passes tests."""

    @pytest.mark.asyncio
    async def test_full_pass(self, strategy: CRSBenchPatchVerifyStrategy) -> None:
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),  # find patch
            _make_exec_result(),                                      # patch apply
            _make_exec_result(),                                      # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(),                                      # run POV 1 (no crash)
            _make_exec_result(),                                      # test -f test.sh (exists)
            _make_exec_result(),                                      # bash test.sh (pass)
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert isinstance(result, Score)
        assert result.value == pytest.approx(1.0)
        assert result.explanation is not None
        assert "VALID" in result.explanation

    @pytest.mark.asyncio
    async def test_no_test_script_configured(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """When test_script is empty string, tests are skipped → 1.0."""
        ctx = _make_ctx(criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),  # find patch
            _make_exec_result(),                                      # patch apply
            _make_exec_result(),                                      # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(),                                      # run POV (no crash)
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_test_script_file_not_found(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """test_script is set but file doesn't exist on disk → tests skipped → 1.0."""
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),  # find patch
            _make_exec_result(),                                      # patch apply
            _make_exec_result(),                                      # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(),                                      # run POV (no crash)
            _make_exec_result(returncode=1),                          # test -f (not found)
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_max_score_scaling(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """max_score of 5.0 should produce a final score of 5.0."""
        ctx = _make_ctx(max_score=5.0, criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),
            _make_exec_result(),
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),
            _make_exec_result(),
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(5.0)


class TestPatchVerifyScore0_5:
    """Score 0.5: patch builds, fixes crashes, but unit tests fail."""

    @pytest.mark.asyncio
    async def test_tests_fail(self, strategy: CRSBenchPatchVerifyStrategy) -> None:
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),  # find patch
            _make_exec_result(),                                      # patch apply
            _make_exec_result(),                                      # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(),                                      # run POV (no crash)
            _make_exec_result(),                                      # test -f (exists)
            _make_exec_result(returncode=1, stderr="FAIL: test_foo"),  # bash test.sh fails
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.5)
        assert result.explanation is not None
        assert "breaks" in result.explanation.lower() or "tests" in result.explanation.lower()

    @pytest.mark.asyncio
    async def test_tests_fail_with_max_score(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """0.5 * max_score when max_score != 1.0."""
        ctx = _make_ctx(max_score=10.0)
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),
            _make_exec_result(),
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),
            _make_exec_result(),
            _make_exec_result(),
            _make_exec_result(returncode=1, stderr="assertion error"),
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(5.0)


class TestPatchVerifyScore0_0:
    """Score 0.0: various failure modes."""

    @pytest.mark.asyncio
    async def test_no_patch_found_empty_stdout(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """find returns 0 but no output → no patch file."""
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout=""),  # find returns no files
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "No .diff" in (result.explanation or "")

    @pytest.mark.asyncio
    async def test_no_patch_found_find_fails(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """find returns non-zero (directory doesn't exist)."""
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(returncode=1, stderr="No such directory"),
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_patch_does_not_apply(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/bad.diff\n"),
            _make_exec_result(returncode=1, stderr="FAILED -- saving rejects"),
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "failed to apply" in (result.explanation or "").lower()

    @pytest.mark.asyncio
    async def test_build_fails(self, strategy: CRSBenchPatchVerifyStrategy) -> None:
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),                                       # patch apply OK
            _make_exec_result(returncode=2, stderr="error: undefined"),  # build fails
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "build failed" in (result.explanation or "").lower()

    @pytest.mark.asyncio
    async def test_patched_binary_still_crashes(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),  # find patch
            _make_exec_result(),                                      # patch apply
            _make_exec_result(),                                      # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(returncode=1, stderr="ASAN: heap-buffer-overflow"),  # crash!
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "still crashes" in (result.explanation or "").lower()

    @pytest.mark.asyncio
    async def test_no_pov_files_found(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """No POV files in pov_dir → score 0.0."""
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),
            _make_exec_result(),
            _make_exec_result(stdout=""),  # no POVs
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "No POV" in (result.explanation or "")


class TestPatchVerifyEdgeCases:
    """Edge cases: multiple patches, multiple POVs, custom build script."""

    @pytest.mark.asyncio
    async def test_multiple_patch_files_picks_first(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """When multiple .diff files exist, the first is used."""
        ctx = _make_ctx(criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/a.diff\n/submit/patches/b.diff\n"),
            _make_exec_result(),  # patch apply (a.diff)
            _make_exec_result(),  # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),
            _make_exec_result(),  # run POV
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(1.0)
        # Verify the first patch file was used in the apply command
        apply_call = sbx.exec.call_args_list[1]
        assert "/submit/patches/a.diff" in str(apply_call)

    @pytest.mark.asyncio
    async def test_multiple_povs_all_must_pass(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """All POV files must pass (no crash) for a non-zero score."""
        ctx = _make_ctx(criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),  # patch apply
            _make_exec_result(),  # build
            _make_exec_result(
                stdout="/workspace/povs/pov1.bin\n/workspace/povs/pov2.bin\n/workspace/povs/pov3.bin\n"
            ),
            _make_exec_result(),  # POV 1 pass
            _make_exec_result(),  # POV 2 pass
            _make_exec_result(),  # POV 3 pass
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_multiple_povs_one_crashes(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """If any POV crashes, score is 0.0."""
        ctx = _make_ctx(criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),  # patch apply
            _make_exec_result(),  # build
            _make_exec_result(
                stdout="/workspace/povs/pov1.bin\n/workspace/povs/pov2.bin\n"
            ),
            _make_exec_result(),                                      # POV 1 pass
            _make_exec_result(returncode=1, stderr="ASAN detected"),  # POV 2 crashes
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_custom_build_script(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """When build_script is set, it's used instead of default make."""
        ctx = _make_ctx(
            criteria_extra={
                "build_script": "/workspace/source/build_asan.sh",
                "test_script": "",
            },
        )
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),  # patch apply
            _make_exec_result(),  # build via custom script
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),
            _make_exec_result(),  # POV pass
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(1.0)
        # Verify build command used custom script
        build_call = sbx.exec.call_args_list[2]
        args_str = str(build_call)
        assert "build_asan.sh" in args_str

    @pytest.mark.asyncio
    async def test_non_domain_criteria_type(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """Criteria that is not DomainCriteria → score 0.0."""
        # ScorerConfig is frozen and validates criteria via a union type,
        # so we use model_construct to bypass validation and inject a
        # non-DomainCriteria object.
        non_domain = MagicMock(spec=[])
        scorer = ScorerConfig.model_construct(
            scorer_name="submission",
            strategy="crsbench_patch_verify",
            criteria=non_domain,
            max_score=1.0,
        )
        ctx = ScoringContext(
            submission="",
            tool_steps=(),
            messages=(ChatMessageUser(content="test"),),
            target="",
            task_id="test_task",
            domain="crsbench",
            metadata={},
            scorer=scorer,
        )

        result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "Expected DomainCriteria" in (result.explanation or "")
