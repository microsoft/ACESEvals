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

# Remove nested .git directories so subdirectories (e.g. mock-c/, curl/)
# are tracked as regular files instead of being treated as embedded
# submodules.  Harmless no-op when none exist.
find . -mindepth 2 -name .git -exec rm -rf {} + 2>/dev/null || true

# Ignore build artifacts so they never pollute git diff output.
cat > .gitignore <<'IGNORE'
*.o
*.a
*.so
*.class
*.jar
*.pyc
__pycache__/
IGNORE

git init
git checkout -b main 2>/dev/null || true
git config user.email "sandbox@saber"
git config user.name "sandbox"
git add -A
git commit --allow-empty -m "initial" --quiet
"""


# Parameters consumed by setup hooks (setup.py) or crsbench itself
# that must NOT leak through to the agent factory via **kwargs.
_DOMAIN_ONLY_PARAMS = frozenset({
    "dataset",
    "data_dir",
    "build",
    "rebuild_images",
})


@task
def crsbench(**kwargs: str | None) -> Task:
    """CRSBench vulnerability patching domain.

    Vulnerability patching benchmark based on CRSBench — agent receives
    vulnerable source code, crash-triggering POVs, and must write a
    source-code patch that fixes the crash without breaking functionality.

    Setup hooks (data download, image build, task generation) are
    auto-discovered via ``get_hooks()`` in ``setup.py``.

    Args:
        **kwargs: Keyword arguments forwarded to ``create_task``
            (e.g., task_filter, agent, rebuild, run_preflight,
            keep_permanent, persona_file, dataset, build, rebuild_images).

    Returns:
        Fully configured inspect_ai Task.
    """
    # Strip domain-only params so they don't leak to the agent factory
    # (e.g. react() would fail on unknown kwargs like 'dataset').
    task_kwargs = {k: v for k, v in kwargs.items() if k not in _DOMAIN_ONLY_PARAMS}
    result = create_task(**task_kwargs)
    # Inject git init setup into every sample so agents can use `git diff`
    # to generate patches instead of manually crafting unified diffs.
    # Unconditionally overwrite — git init must always run, even if YAML
    # defines a setup script via a future TaskConfig.setup field.
    for sample in result.dataset:
        sample.setup = _GIT_INIT_SETUP
    return result
