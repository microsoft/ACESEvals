"""CTI Realm - Cyber Threat Intelligence domain for Inspect AI.

This module exposes the CTI Realm domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/cti_realm --model openai/gpt-4
    inspect eval domains/cti_realm -T task_filter=linux_* --model anthropic/claude-3-opus
"""

from inspect_ai import Task, task

from saber.task import create_task


@task
def cti_realm(**kwargs: str | None) -> Task:
    """CTI Realm - Cyber Threat Intelligence domain.

    Cybersecurity threat intelligence analysis benchmark with detection rule
    development and sophisticated 5-checkpoint evaluation system.

    Args:
        **kwargs: Keyword arguments forwarded to ``create_task``
            (e.g., task_filter, agent, rebuild, run_preflight,
            keep_permanent, persona_file).

    Returns:
        Fully configured inspect_ai Task.
    """
    return create_task(**kwargs)
