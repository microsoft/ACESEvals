"""CRSBench domain tools for sandbox execution.

Exports the ``submit_patch`` tool and a factory function for registration.
"""

from collections.abc import Callable
from pathlib import Path

from inspect_ai.tool import Tool

from .submit_patch import submit_patch

__all__ = ["get_tools", "submit_patch"]


def get_tools(
    domain_root: Path,  # noqa: ARG001
) -> dict[str, Callable[..., Tool]]:
    """Return CRSBench domain tools for registration.

    Auto-discovered by ``create_task`` when a ``tools/`` package is
    present in the domain directory.

    Args:
        domain_root: Path to the domain root directory.

    Returns:
        Mapping of tool name to tool factory callable.
    """
    return {
        "submit_patch": submit_patch,
    }
