"""Submit patch tool for CRSBench bug-fix tasks."""

from __future__ import annotations

from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox

_DIFF_MARKERS = ("---", "+++", "@@", "diff ")


@tool
def submit_patch(timeout: int = 60) -> Tool:
    """Submit a unified diff patch file for verification.

    The agent provides the path to a patch file in the workspace.
    The tool validates it looks like a unified diff and copies it to
    ``/submit/patches/`` for the scorer to pick up.

    Args:
        timeout: Command timeout in seconds.
    """

    async def execute(patch_path: str) -> str:
        """Submit a patch file for verification.

        Args:
            patch_path: Absolute path to the patch file in the sandbox.

        Returns:
            Success or error message.
        """
        sbx = sandbox()

        # 1. Validate file exists
        check = await sbx.exec(["test", "-f", patch_path], timeout=timeout)
        if check.returncode != 0:
            return f"ERROR: File not found: {patch_path}"

        # 2. Basic unified diff validation
        head = await sbx.exec(["head", "-5", patch_path], timeout=timeout)
        content = head.stdout
        if not any(marker in content for marker in _DIFF_MARKERS):
            return (
                f"ERROR: {patch_path} does not look like a unified diff. "
                "Expected lines starting with '---', '+++', or '@@'."
            )

        # 3. Ensure target directory exists
        await sbx.exec(
            ["mkdir", "-p", "/submit/patches"], timeout=timeout
        )

        # 4. Copy to submit directory
        result = await sbx.exec(
            ["cp", patch_path, "/submit/patches/patch.diff"],
            timeout=timeout,
        )
        if result.returncode != 0:
            return f"ERROR: Failed to copy patch: {result.stderr}"

        return (
            "Patch submitted successfully: /submit/patches/patch.diff\n"
            "The patch will be verified during scoring (apply → rebuild → "
            "run POVs → run tests)."
        )

    return execute
