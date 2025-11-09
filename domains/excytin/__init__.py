"""Excytin database forensics and incident response domain for Inspect AI.

This module exposes the Excytin domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/excytin --model openai/gpt-4
    inspect eval domains/excytin -T task_filter=forensics_* --model anthropic/claude-3-opus
"""

# Import the task from the main module
# Note: __init__.py files are excluded from Inspect AI's task discovery,
# so the actual @task decorator is in excytin.py
from .excytin import excytin

__all__ = ["excytin"]
