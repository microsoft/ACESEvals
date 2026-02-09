"""CyBench security challenges domain for Inspect AI.

This module exposes the CyBench domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/cybench --model openai/gpt-4
    inspect eval domains/cybench -T task_filter=labyrinth_* --model openai/gpt-4
"""

from pathlib import Path

from inspect_ai import task

# Import SABER's task factory
# External SABER is installed as a package, so import from saber.inspect_ai
from saber.inspect_ai import create_domain_task

# Get the workspace root (parent of domains/)
# This file is at: domains/cybench/cybench.py
# We need: /path/to/workspace/domains (the domains directory itself)
_domains_root = Path(__file__).resolve().parent.parent

# Create the task factory (returns a callable that Inspect AI will invoke)
_cybench_factory = create_domain_task(
    domain_slug="cybench",
    domains_root=_domains_root,
    default_agent="react",  # Default agent for CyBench
)


# Wrap in @task decorator for Inspect AI discovery
# The @task decorator registers this with Inspect AI's task registry
@task
def cybench(**kwargs):
    """CyBench security challenges domain.
    
    Dynamically loads tasks from the running SABER server.
    
    Args:
        rest_port: REST API port (default: 8000)
        mcp_port: MCP API port (default: 8001)
        task_filter: Optional task filter (exact match, glob pattern, or comma-separated)
            - Single exact: "xss_0_flag_capture"
            - Single glob: "xss_*"
            - Multiple patterns (OR logic): "xss_*,sql_*"
            - Mixed: "xss_0_flag_capture,sql_*,cmd_*"
        agent: Agent implementation to use (default: "react")
        log_level: Logging level for domain services (default: "INFO")
        build: Build missing images before starting (default: False)
        rebuild: Remove and rebuild images matching this prefix (e.g., 'server')
        rebuild_all: Remove and rebuild all images (default: False)
        stop_saber_after: Stop SABER domain after task completes (default: False).
            If False (default), server stays running for faster re-runs.
    
    Returns:
        Inspect AI Task with SABER cybench dataset loaded from server
    
    Examples:
        # Basic evaluation (server stays running after)
        inspect eval domains/cybench --model openai/gpt-4
        
        # Use custom domain-specific agent
        inspect eval domains/cybench --model openai/gpt-4 -T agent=custom_example
        
        # Build missing images first
        inspect eval domains/cybench --model openai/gpt-4 -T build=true
        
        # Rebuild all images (clean slate)
        inspect eval domains/cybench --model openai/gpt-4 -T rebuild_all=true
        
        # Stop server after evaluation completes
        inspect eval domains/cybench --model openai/gpt-4 -T stop_saber_after=true
        
        # Filter to specific tasks
        inspect eval domains/cybench --model openai/gpt-4 -T task_filter="labyrinth_*"
    """
    return _cybench_factory(**kwargs)
