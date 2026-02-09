"""saber_dual adversarial security agentic benchmarking

This module exposes the saber_dual domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/saber_dual --model openai/gpt-4
    inspect eval domains/saber_dual -T task_filter="saber_dual_*" --model anthropic/claude-3-opus
"""

import sys
from pathlib import Path

from inspect_ai import task

# Import SABER's task factory
# External SABER is installed as a package, so import from saber.inspect_ai
from saber.inspect_ai import create_domain_task

# Add the saber_dual domain to the path so we can import its scoring module
_saber_dual_root = Path(__file__).resolve().parent
if str(_saber_dual_root) not in sys.path:
    sys.path.insert(0, str(_saber_dual_root))

# Import SABER Dual scoring to register custom scorers (blue_team_defense, etc.)
# This must happen before evaluation so the scorer registry has the custom strategies
# The module auto-registers scorers on import
from server.scoring import register_saber_dual_scorers

# Explicitly call registration in case auto-registration didn't fire
register_saber_dual_scorers()

# Get the workspace root (parent of domains/)
# This file is at: domains/saber_dual/saber_dual.py
# We need: /path/to/workspace/domains (the domains directory itself)
_domains_root = Path(__file__).resolve().parent.parent

# Create the task factory (returns a callable that Inspect AI will invoke)
_saber_dual_factory = create_domain_task(
    domain_slug="saber_dual",
    domains_root=_domains_root,
    default_agent="react",
)


# Wrap in @task decorator for Inspect AI discovery
# The @task decorator registers this with Inspect AI's task registry
@task
def saber_dual(**kwargs):
    """saber_dual adversarial security agentic benchmark
    
    Dynamically loads tasks from the running SABER server.
    
    Args:
        rest_port: REST API port (default: 8000)
        mcp_port: MCP API port (default: 8001)
        task_filter: Optional task filter (exact match, glob pattern, or comma-separated)
        log_level: Logging level for domain services (default: "INFO")
        build: Build missing images before starting (default: False)
        rebuild: Remove and rebuild images matching this prefix (e.g., 'server')
        rebuild_all: Remove and rebuild all images (default: False)
        stop_saber_after: Stop SABER domain after task completes (default: False).
            If False (default), server stays running for faster re-runs.
    
    Returns:
        Inspect AI Task with SABER saber_dual dataset loaded from server
    
    Examples:
        # Basic evaluation (server stays running after)
        inspect eval domains/saber_dual --model openai/gpt-4
        
        # Build missing images first
        inspect eval domains/saber_dual --model openai/gpt-4 -T build=true
        
        # Rebuild all images (clean slate)
        inspect eval domains/saber_dual --model openai/gpt-4 -T rebuild_all=true
        
        # Stop server after evaluation completes
        inspect eval domains/saber_dual --model openai/gpt-4 -T stop_saber_after=true
        
    # Filter to specific tasks
    inspect eval domains/saber_dual --model openai/gpt-4 -T task_filter="saber_dual_blue_team"
    """
    return _saber_dual_factory(**kwargs)
