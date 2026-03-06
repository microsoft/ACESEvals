"""Tests for CRSBench patch verification scoring strategy.

Covers all three score tiers (1.0, 0.5, 0.0) and edge cases (multiple
patches, multiple POVs, missing test script, build failures, etc.).
"""

from __future__ import annotations

from pathlib import Path
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
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
            _make_exec_result(),                                      # patch apply
            _make_exec_result(),                                      # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(),                                      # run POV 1 (no crash)
            _make_exec_result(),                                      # test -f test.sh (exists)
            _make_exec_result(),                                      # chmod +x scripts
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
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
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
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
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
    async def test_patch_already_applied_proceeds_to_build(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """Patch already applied: forward fails, reverse dry-run succeeds → continue to build/test → 1.0."""
        ctx = _make_ctx(criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),  # find patch
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
            _make_exec_result(returncode=1),                          # patch apply fails
            _make_exec_result(returncode=0),                          # reverse dry-run succeeds → already applied
            _make_exec_result(),                                      # build succeeds
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(),                                      # run POV (no crash)
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert isinstance(result, Score)
        assert result.value == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_max_score_scaling(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """max_score of 5.0 should produce a final score of 5.0."""
        ctx = _make_ctx(max_score=5.0, criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),  # normalise patch paths
            _make_exec_result(),  # reverse + cleanup
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
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
            _make_exec_result(),                                      # patch apply
            _make_exec_result(),                                      # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(),                                      # run POV (no crash)
            _make_exec_result(),                                      # test -f (exists)
            _make_exec_result(),                                      # chmod +x scripts
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
            _make_exec_result(),  # normalise patch paths
            _make_exec_result(),  # reverse + cleanup
            _make_exec_result(),
            _make_exec_result(),
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),
            _make_exec_result(),
            _make_exec_result(),
            _make_exec_result(),  # chmod +x scripts
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
            _make_exec_result(),                                                    # normalise patch paths
            _make_exec_result(),                                                    # reverse + cleanup
            _make_exec_result(returncode=1, stderr="FAILED -- saving rejects"),  # patch apply fails
            _make_exec_result(returncode=1),  # reverse dry-run also fails → truly bad patch
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "failed to apply" in (result.explanation or "").lower()

    @pytest.mark.asyncio
    async def test_patch_truly_fails_with_stdout_error(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """Patch fails with error in stdout (not stderr) → stdout captured in explanation."""
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/bad.diff\n"),             # find patch
            _make_exec_result(),                                                    # normalise patch paths
            _make_exec_result(),                                                    # reverse + cleanup
            _make_exec_result(returncode=1, stdout="FAILED -- saving rejects", stderr=""),  # apply fails
            _make_exec_result(returncode=1),                                      # reverse dry-run also fails
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        explanation = result.explanation or ""
        assert "FAILED" in explanation or "saving rejects" in explanation

    @pytest.mark.asyncio
    async def test_patch_already_applied_but_crashes_still(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """Patch already applied (reverse dry-run succeeds) but POV still crashes → 0.0."""
        ctx = _make_ctx(criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),  # find patch
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
            _make_exec_result(returncode=1),                          # patch apply fails
            _make_exec_result(returncode=0),                          # reverse dry-run succeeds → already applied
            _make_exec_result(),                                      # build succeeds
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),   # find POVs
            _make_exec_result(returncode=1, stderr="ASAN: crash"),     # POV crashes
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(0.0)
        assert "still crashes" in (result.explanation or "").lower()

    @pytest.mark.asyncio
    async def test_build_fails(self, strategy: CRSBenchPatchVerifyStrategy) -> None:
        ctx = _make_ctx()
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),                                       # normalise patch paths
            _make_exec_result(),                                       # reverse + cleanup
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
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
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
            _make_exec_result(),  # normalise patch paths
            _make_exec_result(),  # reverse + cleanup
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
            _make_exec_result(),  # normalise patch paths
            _make_exec_result(),  # reverse + cleanup
            _make_exec_result(),  # patch apply (a.diff)
            _make_exec_result(),  # build
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),
            _make_exec_result(),  # run POV
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(1.0)
        # Verify the first patch file was passed to the normaliser
        normalise_call = sbx.exec.call_args_list[1]
        assert "/submit/patches/a.diff" in str(normalise_call)

    @pytest.mark.asyncio
    async def test_multiple_povs_all_must_pass(
        self, strategy: CRSBenchPatchVerifyStrategy
    ) -> None:
        """All POV files must pass (no crash) for a non-zero score."""
        ctx = _make_ctx(criteria_extra={"test_script": ""})
        sbx = _make_sandbox_mock([
            _make_exec_result(stdout="/submit/patches/fix.diff\n"),
            _make_exec_result(),  # normalise patch paths
            _make_exec_result(),  # reverse + cleanup
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
            _make_exec_result(),                                      # normalise patch paths
            _make_exec_result(),                                      # reverse + cleanup
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
            _make_exec_result(),  # normalise patch paths
            _make_exec_result(),  # reverse + cleanup
            _make_exec_result(),  # patch apply
            _make_exec_result(),  # build via custom script
            _make_exec_result(stdout="/workspace/povs/pov1.bin\n"),
            _make_exec_result(),  # POV pass
        ])

        with patch("crsbench.scoring.patch_verify.sandbox", return_value=sbx):
            result = await strategy.score(ctx, None)

        assert result.value == pytest.approx(1.0)
        # Verify build command used custom script
        build_call = sbx.exec.call_args_list[4]
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


# ---------------------------------------------------------------------------
# Patch normaliser (inline Python script) tests
# ---------------------------------------------------------------------------


class TestPatchNormaliser:
    """Direct tests for the inline patch normaliser script.

    The normaliser runs as an inline Python snippet inside the Docker sandbox.
    These tests verify syntax validity and hunk-header count correction by
    running the script locally via ``subprocess``.
    """

    @staticmethod
    def _build_normaliser_script(source_dir: str) -> str:
        """Reconstruct the normaliser script with the given source_dir."""
        return "\n".join([
            "import re, sys, os, pathlib",
            f"src = {str(source_dir)!r}",
            "def resolve(p):",
            "  if os.path.exists(os.path.join(src, p)): return p",
            "  base = os.path.basename(p)",
            "  for root, dirs, files in os.walk(src):",
            "    if base in files:",
            "      return os.path.relpath(os.path.join(root, base), src)",
            "  return p",
            "lines = pathlib.Path(sys.argv[1]).read_text()",
            "out = []",
            "for ln in lines.splitlines():",
            "  m = re.match(r'^(---|\\+\\+\\+)\\s+(.*)', ln)",
            "  if not m:",
            "    out.append(ln + chr(10))",
            "    continue",
            "  raw = m.group(2).replace(src + '/', '').lstrip('/')",
            "  raw = re.sub(r'^[ab]/', '', raw)",
            "  raw = re.sub(r'\\t.*', '', raw)",
            "  raw = re.sub(r'\\.(bak|orig|old|new)(\\s.*|[0-9].*)?$', '', raw)",
            "  raw = raw.rstrip('~')",
            "  raw = resolve(raw)",
            "  prefix = 'a/' if m.group(1) == '---' else 'b/'",
            "  out.append(m.group(1) + ' ' + prefix + raw + chr(10))",
            "fixed = []",
            "i = 0",
            "while i < len(out):",
            "  hm = re.match(r'^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@(.*)', out[i])",
            "  if not hm:",
            "    fixed.append(out[i])",
            "    i += 1",
            "    continue",
            "  oc = nc = 0",
            "  j = i + 1",
            "  while j < len(out):",
            "    hl = out[j].rstrip(chr(10))",
            "    if hl.startswith('@@') or hl.startswith('diff ') or re.match(r'^(---|\\+\\+\\+) [ab]/', hl):",
            "      break",
            "    if hl.startswith('+'):",
            "      nc += 1",
            "    elif hl.startswith('-'):",
            "      oc += 1",
            "    elif hl.startswith(chr(92)):",
            "      pass",
            "    else:",
            "      oc += 1",
            "      nc += 1",
            "    j += 1",
            "  fixed.append('@@ -%s,%d +%s,%d @@%s' % (hm.group(1), oc, hm.group(2), nc, hm.group(3)) + chr(10))",
            "  i += 1",
            "out = fixed",
            "pathlib.Path(sys.argv[2]).write_text(''.join(out))",
        ])

    def test_syntax_valid(self, tmp_path: Path) -> None:
        """Normaliser script is syntactically valid Python."""
        script = self._build_normaliser_script(str(tmp_path))
        compile(script, "<normaliser>", "exec")  # raises SyntaxError on failure

    def test_hunk_header_counts_corrected(self, tmp_path: Path) -> None:
        """Wrong @@ counts are recalculated to match actual hunk content."""
        import subprocess

        # Build a source tree so resolve() can find mock.c
        src_dir = tmp_path / "source" / "mock-c"
        src_dir.mkdir(parents=True)
        (src_dir / "mock.c").write_text("/* dummy */")

        # Patch with WRONG hunk counts: claims -18,8 +18,18 but real is 7/9
        bad_patch = (
            "--- a/mock-c/mock.c\n"
            "+++ b/mock-c/mock.c\n"
            "@@ -18,8 +18,18 @@ void parse_buffer_section(...) {\n"
            "   uint32_t buf_size = ((uint32_t *)data)[0];\n"
            "   uint32_t idx = ((uint32_t *)data)[1];\n"
            "   if (buf_size + 8 != size)\n"
            "     return;\n"
            "+  if (idx > buf_size)\n"
            "+    return;\n"
            "   uint8_t *buf = (uint8_t *)malloc(buf_size);\n"
            "-  memcpy(&buf[idx], &data[8],  buf_size);\n"
            "+  memcpy(&buf[idx], &data[8], buf_size - idx);\n"
            " }\n"
        )
        patch_file = tmp_path / "bad.diff"
        patch_file.write_text(bad_patch)

        out_file = tmp_path / "fixed.diff"
        # Use sys.argv[2] for output path instead of hardcoded /tmp/_n.diff
        script = self._build_normaliser_script(str(tmp_path / "source"))
        result = subprocess.run(
            ["python3", "-c", script, str(patch_file), str(out_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        output = out_file.read_text()
        # Old: 6 context + 1 delete = 7; New: 6 context + 3 add = 9
        # (the function annotation after @@ is preserved)
        assert "@@ -18,7 +18,9 @@ void parse_buffer_section(...) {" in output

    def test_correct_counts_unchanged(self, tmp_path: Path) -> None:
        """Patch with already-correct counts passes through unchanged."""
        import subprocess

        src_dir = tmp_path / "source" / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "hello.c").write_text("/* dummy */")

        good_patch = (
            "--- a/src/hello.c\n"
            "+++ b/src/hello.c\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            " line2\n"
            "+added\n"
            " line3\n"
        )
        patch_file = tmp_path / "good.diff"
        patch_file.write_text(good_patch)

        out_file = tmp_path / "out.diff"
        script = self._build_normaliser_script(str(tmp_path / "source"))
        result = subprocess.run(
            ["python3", "-c", script, str(patch_file), str(out_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        output = out_file.read_text()
        assert "@@ -1,3 +1,4 @@" in output

    def test_absolute_paths_normalised(self, tmp_path: Path) -> None:
        """Absolute paths in --- / +++ are resolved to relative a/b/ paths."""
        import subprocess

        src_dir = tmp_path / "source" / "lib"
        src_dir.mkdir(parents=True)
        (src_dir / "util.c").write_text("/* dummy */")

        abs_patch = (
            "--- /workspace/source/lib/util.c\n"
            "+++ /workspace/source/lib/util.c\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
        )
        patch_file = tmp_path / "abs.diff"
        patch_file.write_text(abs_patch)

        out_file = tmp_path / "out.diff"
        script = self._build_normaliser_script(str(tmp_path / "source"))
        result = subprocess.run(
            ["python3", "-c", script, str(patch_file), str(out_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

        output = out_file.read_text()
        # Absolute paths should NOT survive; basename resolve should find lib/util.c
        assert "--- a/" in output
        assert "+++ b/" in output
