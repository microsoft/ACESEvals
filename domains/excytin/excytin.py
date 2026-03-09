"""Excytin database forensics and incident response domain for Inspect AI.

This module exposes the Excytin domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/excytin --model openai/gpt-4
    inspect eval domains/excytin -T task_filter=forensics_* --model anthropic/claude-3-opus
"""

from pathlib import Path

from inspect_ai import task

# Import SABER's task factory
# External SABER is installed as a package, so import from saber.inspect_ai
from saber.inspect_ai import create_domain_task

# ---------------------------------------------------------------------------
# Monkey-patch: enable adaptive thinking + output_config for Anthropic models
# ---------------------------------------------------------------------------
# inspect_ai hardcodes thinking={"type": "enabled", ...} but we need
# {"type": "adaptive"} and output_config={"effort": "high"}.
# This patch overrides completion_config() so that when --reasoning-tokens
# is passed, the API request uses adaptive thinking mode.
# ---------------------------------------------------------------------------
from inspect_ai.model._providers.anthropic import AnthropicAPI  # noqa: E402

_original_completion_config = AnthropicAPI.completion_config


def _patched_completion_config(self, config):  # type: ignore[override]
    params, headers, betas = _original_completion_config(self, config)
    # Switch from "enabled" → "adaptive" thinking mode (no budget_tokens needed)
    if "thinking" in params:
        params["thinking"] = {"type": "adaptive"}
    # Set output effort to high (default for Anthropic, but explicit)
    params["output_config"] = {"effort": "high"}
    return params, headers, betas


AnthropicAPI.completion_config = _patched_completion_config  # type: ignore[assignment]

# Get the workspace root (parent of domains/)
# This file is at: domains/excytin/excytin.py
# We need: /path/to/workspace/domains (the domains directory itself)
_domains_root = Path(__file__).resolve().parent.parent

# Create the task factory (returns a callable that Inspect AI will invoke)
_excytin_factory = create_domain_task("excytin", _domains_root)


# Wrap in @task decorator for Inspect AI discovery
# The @task decorator registers this with Inspect AI's task registry
@task
def excytin(**kwargs):
    """Excytin database forensics and incident response domain.
    
    Dynamically loads tasks from the running SABER server.
    
    Args:
        rest_port: REST API port (default: 8000)
        mcp_port: MCP API port (default: 8001)
        task_filter: Optional task filter (exact match, glob pattern, or comma-separated)
            - Single exact: "xss_0_flag_capture"
            - Single glob: "xss_*"
            - Multiple patterns (OR logic): "xss_*,sql_*"
            - Mixed: "xss_0_flag_capture,sql_*,cmd_*"
        log_level: Logging level for domain services (default: "INFO")
        build: Build missing images before starting (default: False)
        rebuild: Remove and rebuild images matching this prefix (e.g., 'server')
        rebuild_all: Remove and rebuild all images (default: False)
        stop_saber_after: Stop SABER domain after task completes (default: False).
            If False (default), server stays running for faster re-runs.
    
    Returns:
        Inspect AI Task with SABER excytin dataset loaded from server
    
    Examples:
        # Basic evaluation (server stays running after)
        inspect eval domains/excytin --model openai/gpt-4
        
        # Build missing images first
        inspect eval domains/excytin --model openai/gpt-4 -T build=true
        
        # Rebuild all images (clean slate)
        inspect eval domains/excytin --model openai/gpt-4 -T rebuild_all=true
        
        # Stop server after evaluation completes
        inspect eval domains/excytin --model openai/gpt-4 -T stop_saber_after=true
        
        # Filter to specific tasks
        inspect eval domains/excytin --model openai/gpt-4 -T task_filter="forensics_*"
    """
    return _excytin_factory(**kwargs)
