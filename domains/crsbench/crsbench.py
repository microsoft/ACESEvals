"""CRSBench vulnerability patching domain for Inspect AI.

This module exposes the CRSBench domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/crsbench --model openai/gpt-4
    inspect eval domains/crsbench -T task_filter=sanity_* --model openai/gpt-4
"""

from inspect_ai import Task, task

from saber.task import create_task

from .setup import DownloadBenchmarkData


@task
def crsbench(**kwargs: str | None) -> Task:
    """CRSBench vulnerability patching domain.

    Vulnerability patching benchmark based on CRSBench — agent receives
    vulnerable source code, crash-triggering POVs, and must write a
    source-code patch that fixes the crash without breaking functionality.

    Args:
        **kwargs: Keyword arguments forwarded to ``create_task``
            (e.g., task_filter, agent, rebuild, run_preflight,
            keep_permanent, persona_file).

    Returns:
        Fully configured inspect_ai Task.
    """
    return create_task(
        setup_hooks=[DownloadBenchmarkData()],
        **kwargs,
    )
