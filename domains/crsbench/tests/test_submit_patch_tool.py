"""Tests for the submit_patch tool.

Covers the happy path (valid diff copied), file-not-found, non-diff file,
and copy-failure scenarios.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> MagicMock:
    """Build a mock mimicking the sandbox exec() return value."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubmitPatchTool:
    """Unit tests for submit_patch @tool function."""

    @pytest.mark.asyncio
    async def test_happy_path_valid_diff(self) -> None:
        """Valid unified diff is copied to /submit/patches/patch.diff."""
        from crsbench.tools.submit_patch import submit_patch

        diff_content = (
            "--- a/src/main.c\n"
            "+++ b/src/main.c\n"
            "@@ -10,6 +10,7 @@\n"
            " int main() {\n"
            "+    return 0;\n"
            " }\n"
        )
        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                # test -f → file exists
                _make_exec_result(returncode=0),
                # head -5 → valid diff content
                _make_exec_result(returncode=0, stdout=diff_content),
                # mkdir -p → success
                _make_exec_result(returncode=0),
                # cp → success
                _make_exec_result(returncode=0),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch()
            result = await execute(patch_path="/workspace/my.patch")

        assert "successfully" in result.lower()
        assert "/submit/patches/patch.diff" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        """Returns error when the patch file does not exist."""
        from crsbench.tools.submit_patch import submit_patch

        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                # test -f → file missing
                _make_exec_result(returncode=1),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch()
            result = await execute(patch_path="/workspace/nonexistent.patch")

        assert "error" in result.lower()
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_file_not_unified_diff(self) -> None:
        """Returns error when file content has no unified-diff markers."""
        from crsbench.tools.submit_patch import submit_patch

        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                # test -f → file exists
                _make_exec_result(returncode=0),
                # head -5 → plain text, no diff markers
                _make_exec_result(
                    returncode=0,
                    stdout="this is just a text file\nnothing special\n",
                ),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch()
            result = await execute(patch_path="/workspace/readme.txt")

        assert "error" in result.lower()
        assert "unified diff" in result.lower()

    @pytest.mark.asyncio
    async def test_copy_fails(self) -> None:
        """Returns error when the cp command fails."""
        from crsbench.tools.submit_patch import submit_patch

        diff_content = "--- a/f.c\n+++ b/f.c\n@@ -1 +1 @@\n-old\n+new\n"
        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                # test -f → exists
                _make_exec_result(returncode=0),
                # head -5 → valid diff
                _make_exec_result(returncode=0, stdout=diff_content),
                # mkdir -p → success
                _make_exec_result(returncode=0),
                # cp → failure
                _make_exec_result(returncode=1, stderr="Permission denied"),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch()
            result = await execute(patch_path="/workspace/my.patch")

        assert "error" in result.lower()
        assert "copy" in result.lower() or "Permission denied" in result

    @pytest.mark.asyncio
    async def test_diff_marker_detection_with_diff_prefix(self) -> None:
        """Accepts content with 'diff ' marker (git diff format)."""
        from crsbench.tools.submit_patch import submit_patch

        diff_content = "diff --git a/f.c b/f.c\nindex abc..def 100644\n"
        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                _make_exec_result(returncode=0),
                _make_exec_result(returncode=0, stdout=diff_content),
                _make_exec_result(returncode=0),
                _make_exec_result(returncode=0),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch()
            result = await execute(patch_path="/workspace/git.patch")

        assert "successfully" in result.lower()

    @pytest.mark.asyncio
    async def test_custom_timeout_is_forwarded(self) -> None:
        """The configurable timeout is passed to sandbox().exec()."""
        from crsbench.tools.submit_patch import submit_patch

        diff_content = "--- a/f.c\n+++ b/f.c\n@@ -1 +1 @@\n"
        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                _make_exec_result(returncode=0),
                _make_exec_result(returncode=0, stdout=diff_content),
                _make_exec_result(returncode=0),
                _make_exec_result(returncode=0),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch(timeout=30)
            await execute(patch_path="/workspace/my.patch")

        # All four exec calls should use timeout=30
        for call in sbx.exec.call_args_list:
            assert call.kwargs.get("timeout") == 30

    @pytest.mark.asyncio
    async def test_same_file_skips_copy(self) -> None:
        """When patch_path is already the target, skip mkdir and cp."""
        from crsbench.tools.submit_patch import submit_patch

        diff_content = "--- a/f.c\n+++ b/f.c\n@@ -1 +1 @@\n-old\n+new\n"
        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                # test -f → file exists
                _make_exec_result(returncode=0),
                # head -5 → valid diff content
                _make_exec_result(returncode=0, stdout=diff_content),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch()
            result = await execute(patch_path="/submit/patches/patch.diff")

        assert "successfully" in result.lower()
        # Only 2 exec calls: test -f and head -5 (no mkdir, no cp)
        assert sbx.exec.call_count == 2

    @pytest.mark.asyncio
    async def test_same_file_with_trailing_slash_normalization(self) -> None:
        """Normalizable path that resolves to target also skips copy."""
        from crsbench.tools.submit_patch import submit_patch

        diff_content = "--- a/f.c\n+++ b/f.c\n@@ -1 +1 @@\n-old\n+new\n"
        sbx = MagicMock()
        sbx.exec = AsyncMock(
            side_effect=[
                # test -f → file exists
                _make_exec_result(returncode=0),
                # head -5 → valid diff content
                _make_exec_result(returncode=0, stdout=diff_content),
            ]
        )

        with patch("crsbench.tools.submit_patch.sandbox", return_value=sbx):
            execute = submit_patch()
            result = await execute(
                patch_path="/submit/patches/../patches/patch.diff"
            )

        assert "successfully" in result.lower()
        # Only 2 exec calls: test -f and head -5 (no mkdir, no cp)
        assert sbx.exec.call_count == 2
