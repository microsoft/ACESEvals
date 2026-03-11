"""Tests for ValueError handling in bash() and python() tool execute functions.

When an LLM agent generates a command containing a null byte (``\\x00``),
``subprocess.Popen`` raises ``ValueError: embedded null byte``.  The tool
layer should catch this and return the error as tool output so the agent
can recover, rather than crashing the evaluation sample.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inspect_ai.tool._tools._execute import bash, python
from inspect_ai.util._subprocess import ExecResult


class TestBashValueErrorHandling:
    """bash() tool catches ValueError and returns error string."""

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_value_error_returns_error_string(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """ValueError('embedded null byte') is caught and returned as 'Error: ...'."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(side_effect=ValueError("embedded null byte"))
        mock_sandbox_env.return_value = mock_env

        tool_fn = bash()
        result = await tool_fn(cmd="echo hello\x00world")

        assert result == "Error: embedded null byte"

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_other_value_error_returns_error_string(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """Any ValueError (not just null-byte) is caught and returned."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(side_effect=ValueError("some other value error"))
        mock_sandbox_env.return_value = mock_env

        tool_fn = bash()
        result = await tool_fn(cmd="bad command")

        assert result == "Error: some other value error"

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_normal_execution_returns_stdout(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """Successful exec returns stdout normally."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(
            return_value=ExecResult(
                success=True, returncode=0, stdout="hello\n", stderr=""
            )
        )
        mock_sandbox_env.return_value = mock_env

        tool_fn = bash()
        result = await tool_fn(cmd="echo hello")

        assert result == "hello\n"

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_normal_execution_includes_stderr(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """When stderr is present, it is prepended to stdout."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(
            return_value=ExecResult(
                success=False, returncode=1, stdout="", stderr="permission denied"
            )
        )
        mock_sandbox_env.return_value = mock_env

        tool_fn = bash()
        result = await tool_fn(cmd="cat /etc/shadow")

        assert "permission denied" in result

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_non_value_error_propagates(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """Non-ValueError exceptions are NOT caught — they propagate."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(side_effect=RuntimeError("docker daemon crashed"))
        mock_sandbox_env.return_value = mock_env

        tool_fn = bash()
        with pytest.raises(RuntimeError, match="docker daemon crashed"):
            await tool_fn(cmd="echo hi")


class TestPythonValueErrorHandling:
    """python() tool catches ValueError and returns error string."""

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_value_error_returns_error_string(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """ValueError is caught and returned as 'Error: ...'."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(side_effect=ValueError("embedded null byte"))
        mock_sandbox_env.return_value = mock_env

        tool_fn = python()
        result = await tool_fn(code="print('hello\\x00world')")

        assert result == "Error: embedded null byte"

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_normal_execution_returns_stdout(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """Successful exec returns stdout normally."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(
            return_value=ExecResult(
                success=True, returncode=0, stdout="42\n", stderr=""
            )
        )
        mock_sandbox_env.return_value = mock_env

        tool_fn = python()
        result = await tool_fn(code="print(42)")

        assert result == "42\n"

    @pytest.mark.anyio
    @patch("inspect_ai.tool._tools._execute.sandbox_env")
    async def test_non_value_error_propagates(
        self, mock_sandbox_env: MagicMock
    ) -> None:
        """Non-ValueError exceptions propagate to the caller."""
        mock_env = MagicMock()
        mock_env.exec = AsyncMock(side_effect=RuntimeError("container not found"))
        mock_sandbox_env.return_value = mock_env

        tool_fn = python()
        with pytest.raises(RuntimeError, match="container not found"):
            await tool_fn(code="print('hi')")
