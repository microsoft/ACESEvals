"""CRSBench vulnerability patching domain for Inspect AI.

This module exposes the CRSBench domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/crsbench --model openai/gpt-4
    inspect eval domains/crsbench -T task_filter=sanity_* --model openai/gpt-4
"""

from inspect_ai import Task, task

from saber.task import create_task


@task
def crsbench(**kwargs: str | None) -> Task:
    """CRSBench vulnerability patching domain.

    Vulnerability patching benchmark based on CRSBench — agent receives
    vulnerable source code, crash-triggering POVs, and must write a
    source-code patch that fixes the crash without breaking functionality.

    Setup hooks (data download, image build, task generation) are
    auto-discovered via ``get_hooks()`` in ``setup.py``.
    Dataset-to-filter mapping (e.g. ``-T dataset=lite``) is handled
    via ``get_task_filter()`` in ``setup.py``.
    """
    return create_task(**kwargs)
