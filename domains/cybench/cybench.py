"""CyBench security challenges domain for Inspect AI.

This module exposes the CyBench domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/cybench --model openai/gpt-4
    inspect eval domains/cybench -T task_filter=labyrinth_* --model openai/gpt-4
"""

from inspect_ai import Task, task

from saber.task import create_task


@task
def cybench(**kwargs: str | None) -> Task:
    """CyBench security challenges domain.

    Args:
        **kwargs: Keyword arguments forwarded to ``create_task``
            (e.g., task_filter, agent, rebuild, run_preflight,
            keep_permanent, persona_file).

    Returns:
        Fully configured inspect_ai Task.
    """
    return create_task(**kwargs)
