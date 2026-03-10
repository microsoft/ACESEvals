"""CRSBench vulnerability patching domain for Inspect AI.

This module exposes the CRSBench domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/crsbench --model openai/gpt-4
    inspect eval domains/crsbench -T task_filter=sanity_* --model openai/gpt-4
"""

from inspect_ai import Task, task

from saber.task import create_task

_GIT_INIT_SETUP = """\
#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/source
cd /workspace/source
git init -b main
git config user.email "sandbox@saber"
git config user.name "sandbox"
git add -A
git commit --allow-empty -m "initial" --quiet
"""


@task
def crsbench(**kwargs: str | None) -> Task:
    """CRSBench vulnerability patching domain.

    Vulnerability patching benchmark based on CRSBench — agent receives
    vulnerable source code, crash-triggering POVs, and must write a
    source-code patch that fixes the crash without breaking functionality.

    Downloads benchmark data from HuggingFace on first run if not already
    present locally (via auto-discovered setup hooks).

    Args:
        **kwargs: Keyword arguments forwarded to ``create_task``
            (e.g., task_filter, agent, rebuild, run_preflight,
            keep_permanent, persona_file).

    Returns:
        Fully configured inspect_ai Task.
    """
    result = create_task(**kwargs)
    # Inject git init setup into every sample so agents can use `git diff`
    # to generate patches instead of manually crafting unified diffs.
    # Unconditionally overwrite — git init must always run, even if YAML
    # defines a setup script via a future TaskConfig.setup field.
    for sample in result.dataset:
        sample.setup = _GIT_INIT_SETUP
    return result
