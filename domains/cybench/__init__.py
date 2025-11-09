"""CyBench security challenges domain for Inspect AI.

This module exposes the CyBench domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/cybench --model openai/gpt-4
    inspect eval domains/cybench -T task_filter=labyrinth_* --model openai/gpt-4
"""

# Import the task from the main module
# Note: __init__.py files are excluded from Inspect AI's task discovery,
# so the actual @task decorator is in cybench.py
from .cybench import cybench

__all__ = ["cybench"]
