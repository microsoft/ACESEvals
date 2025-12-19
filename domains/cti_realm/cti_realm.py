"""CTI Realm - Cyber Threat Intelligence domain for Inspect AI.

This module exposes the CTI Realm domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval external/saber/domains/cti_realm --model openai/gpt-4
    inspect eval external/saber/domains/cti_realm -T task_filter=linux_* --model anthropic/claude-3-opus
"""

import sys
from pathlib import Path

from inspect_ai import task

# Import SABER's task factory
from saber.inspect_ai import create_domain_task

# Add the cti_realm domain to the path so we can import its scoring module
_cti_realm_root = Path(__file__).resolve().parent
if str(_cti_realm_root) not in sys.path:
    sys.path.insert(0, str(_cti_realm_root))

# Import CTI Realm scoring to register custom scorers (trajectory_analysis, etc.)
# This must happen before evaluation so the scorer registry has the custom strategies
# The module auto-registers scorers on import, but we call it explicitly for clarity
from server.scoring import register_cti_realm_scorers

# Get the domains root
# This file is at: external/saber/domains/cti_realm/cti_realm.py
# We need: external/saber/domains (the domains directory itself)
_domains_root = Path(__file__).resolve().parent.parent

# Create the task factory (returns a callable that Inspect AI will invoke)
_cti_realm_factory = create_domain_task(
    domain_slug="cti_realm",
    domains_root=_domains_root,
    default_agent="react",
)


# Wrap in @task decorator for Inspect AI discovery
@task
def cti_realm(**kwargs):
    """CTI Realm - Cyber Threat Intelligence domain.

    Cybersecurity threat intelligence analysis benchmark with detection rule development
    and sophisticated 5-checkpoint evaluation system. Dynamically loads tasks from the
    running SABER server.

    Args:
        rest_port: REST API port (default: 8000)
        mcp_port: MCP API port (default: 8001)
        task_filter: Optional task filter (exact match or glob pattern)
        agent: Agent implementation to use (default: "react")
        log_level: Logging level for domain services (default: "INFO")
        build: Build missing images before starting (default: False)
        rebuild: Remove and rebuild images matching this prefix (e.g., 'server')
        rebuild_all: Remove and rebuild all images (default: False)
        stop_saber_after: Stop SABER domain after task completes (default: False).
            If False (default), server stays running for faster re-runs.

    Returns:
        Inspect AI Task with SABER cti_realm dataset loaded from server

    Examples:
        # Basic evaluation (server stays running after)
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4

        # Use custom agent
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4 -T agent=custom_example

        # Build missing images first
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4 -T build=true

        # Rebuild all images (clean slate)
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4 -T rebuild_all=true

        # Stop server after evaluation completes
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4 -T stop_saber_after=true

        # Filter to Linux privilege escalation tasks
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4 -T task_filter="linux_*"

        # Run trajectory analysis example task
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4 -T task_filter="cti_trajectory_*"

        # Run a single task
        inspect eval external/saber/domains/cti_realm --model openai/gpt-4 -T task_filter="linux_privilege_escalation_001"
    """
    return _cti_realm_factory(**kwargs)
