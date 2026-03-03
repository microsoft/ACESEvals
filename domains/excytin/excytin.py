"""Excytin database forensics and incident response domain for Inspect AI.

This module exposes the Excytin domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/excytin --model openai/gpt-4
    inspect eval domains/excytin -T task_filter=forensics_* --model anthropic/claude-3-opus
"""

from inspect_ai import Task, task

from saber.task import create_task


@task
def excytin(**kwargs: str | None) -> Task:
    """Excytin database forensics and incident response domain.

    Database forensics and incident response benchmark — agent investigates
    compromised database environments to identify and remediate security
    incidents.

    Args:
        **kwargs: Keyword arguments forwarded to ``create_task``
            (e.g., task_filter, agent, rebuild, run_preflight,
            keep_permanent, persona_file).

    Returns:
        Fully configured inspect_ai Task.
    """
    return create_task(**kwargs)
