"""Shared fixtures and sys.path setup for CTI Realm tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Add domains/ to sys.path so "cti_realm" is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from inspect_ai.model import ChatMessageUser
from saber.config.models import (
    DomainCriteria,
    ScorerConfig,
)
from saber.scoring.context import ScoringContext, ToolStep


def _make_ctx(
    *,
    submission: str = "",
    tool_steps: tuple[ToolStep, ...] = (),
    target: str = "",
    strategy: str = "trajectory_analysis",
    criteria: DomainCriteria | None = None,
    max_score: float = 1.0,
    weight: float = 1.0,
    metadata: dict[str, object] | None = None,
) -> ScoringContext:
    return ScoringContext(
        submission=submission,
        tool_steps=tool_steps,
        messages=(ChatMessageUser(content="test"),),
        target=target,
        task_id="test_task",
        domain="cti_realm",
        metadata=metadata or {},
        scorer=ScorerConfig(
            scorer_name="test",
            strategy=strategy,
            criteria=criteria or DomainCriteria(),
            max_score=max_score,
            weight=weight,
        ),
    )


def _make_tool_step(
    *,
    step_number: int = 1,
    tool_name: str = "execute_kql_query",
    tool_input: dict[str, object] | None = None,
    output: str = "",
    assistant_message: str | None = None,
    reasoning: str | None = None,
) -> ToolStep:
    return ToolStep(
        step_number=step_number,
        tool_name=tool_name,
        tool_input=tool_input or {},
        output=output,
        assistant_message=assistant_message,
        reasoning=reasoning,
    )


@pytest.fixture()
def make_ctx():
    """Fixture exposing the _make_ctx helper."""
    return _make_ctx


@pytest.fixture()
def make_tool_step():
    """Fixture exposing the _make_tool_step helper."""
    return _make_tool_step
