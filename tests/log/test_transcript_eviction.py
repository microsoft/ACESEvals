"""Tests for Transcript.evict_events() (Phase 2, Tasks 3-4).

Covers transcript-level event eviction:
- Eviction by type and working_start boundary (DEC-010)
- JournalBatchRef tracking (DEC-005)
- Preservation of non-evictable event types
- Interleaved event patterns
- Edge cases: empty transcript, zero matches, multiple batches
"""

from __future__ import annotations

from datetime import datetime, timezone

from inspect_ai.event._base import BaseEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.event._score import ScoreEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._recorders.journal import JournalBatchRef
from inspect_ai.log._transcript import Transcript

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logger_event(working_start: float = 0.0) -> LoggerEvent:
    """Create a minimal LoggerEvent with a given working_start."""
    return LoggerEvent(
        message=LoggingMessage(
            level="info",
            message="test",
            created=1000.0,
        ),
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_info_event(working_start: float = 0.0) -> InfoEvent:
    """Create a minimal InfoEvent with a given working_start."""
    return InfoEvent(
        data="test-data",
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_model_event(working_start: float = 0.0) -> ModelEvent:
    """Create a minimal ModelEvent with a given working_start."""
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    return ModelEvent(
        model="test-model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "hello"),
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_score_event(working_start: float = 0.0) -> ScoreEvent:
    """Create a minimal ScoreEvent with a given working_start."""
    from inspect_ai.scorer._metric import Score

    return ScoreEvent(
        score=Score(value=1.0),
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_sandbox_event(working_start: float = 0.0) -> SandboxEvent:
    """Create a minimal SandboxEvent with a given working_start."""
    return SandboxEvent(
        action="exec",
        cmd="echo hello",
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_span_begin_event(working_start: float = 0.0) -> SpanBeginEvent:
    """Create a minimal SpanBeginEvent with a given working_start."""
    return SpanBeginEvent(
        id="span-1",
        name="test-span",
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_span_end_event(working_start: float = 0.0) -> SpanEndEvent:
    """Create a minimal SpanEndEvent with a given working_start."""
    return SpanEndEvent(
        id="span-1",
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_batch_ref(
    batch_index: int = 0,
    event_count: int = 5,
    sample_id: str = "sample-1",
    epoch: int = 1,
) -> JournalBatchRef:
    """Create a JournalBatchRef for testing."""
    return JournalBatchRef(
        batch_index=batch_index,
        event_count=event_count,
        sample_id=sample_id,
        epoch=epoch,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

EVICTABLE_TYPES: tuple[type[BaseEvent], ...] = (LoggerEvent, InfoEvent)


class TestTranscriptEviction:
    def test_evict_removes_logger_events_up_to_cutoff(self) -> None:
        """10 LoggerEvent (ws 0-9) + 5 ModelEvent → evict cutoff=4 → 5 Logger + 5 Model remain."""
        logger_events = [_make_logger_event(working_start=float(i)) for i in range(10)]
        model_events = [_make_model_event(working_start=float(i)) for i in range(5)]
        all_events = logger_events + model_events

        t = Transcript(events=list(all_events))
        assert len(t.events) == 15

        batch_ref = _make_batch_ref(batch_index=0, event_count=5)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=4.0,
        )

        remaining = list(t.events)
        # LoggerEvents with ws 5-9 remain (5) + all 5 ModelEvents
        assert len(remaining) == 10

        remaining_logger = [e for e in remaining if isinstance(e, LoggerEvent)]
        assert len(remaining_logger) == 5
        for e in remaining_logger:
            assert e.working_start > 4.0

        remaining_model = [e for e in remaining if isinstance(e, ModelEvent)]
        assert len(remaining_model) == 5

    def test_evict_preserves_model_score_sandbox_span_events(self) -> None:
        """Model, Score, Sandbox, SpanBegin, SpanEnd events are never removed."""
        events: list[Event] = [
            _make_model_event(working_start=0.0),
            _make_score_event(working_start=1.0),
            _make_sandbox_event(working_start=2.0),
            _make_span_begin_event(working_start=3.0),
            _make_span_end_event(working_start=4.0),
            _make_logger_event(working_start=1.0),  # this one is evictable
        ]

        t = Transcript(events=list(events))
        batch_ref = _make_batch_ref(event_count=1)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=10.0,
        )

        remaining = list(t.events)
        # Only the LoggerEvent should be removed; 5 non-evictable remain
        assert len(remaining) == 5
        remaining_types = {type(e) for e in remaining}
        assert remaining_types == {
            ModelEvent,
            ScoreEvent,
            SandboxEvent,
            SpanBeginEvent,
            SpanEndEvent,
        }

    def test_evict_tracks_journal_ref(self) -> None:
        """After eviction, _journal_refs contains the JournalBatchRef."""
        events = [_make_logger_event(working_start=0.0)]
        t = Transcript(events=list(events))

        batch_ref = _make_batch_ref(batch_index=0, event_count=1)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=0.0,
        )

        refs = t.journal_refs
        assert len(refs) == 1
        assert refs[0] is batch_ref
        assert refs[0].batch_index == 0
        assert refs[0].event_count == 1

    def test_evict_noop_when_no_evictable_events(self) -> None:
        """Transcript with only ModelEvent remains unchanged."""
        events = [_make_model_event(working_start=float(i)) for i in range(5)]
        t = Transcript(events=list(events))

        batch_ref = _make_batch_ref(event_count=0)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=10.0,
        )

        assert len(t.events) == 5
        # No ref appended since 0 events evicted
        assert len(t.journal_refs) == 0

    def test_evict_noop_on_empty_transcript(self) -> None:
        """No crash on empty _events."""
        t = Transcript()
        assert len(t.events) == 0

        batch_ref = _make_batch_ref(event_count=0)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=5.0,
        )

        assert len(t.events) == 0
        assert len(t.journal_refs) == 0

    def test_evict_multiple_batches(self) -> None:
        """Evict twice with different cutoffs; _journal_refs tracks both."""
        events = [_make_logger_event(working_start=float(i)) for i in range(10)]
        t = Transcript(events=list(events))

        # First eviction: cutoff=3 → removes ws 0,1,2,3 (4 events)
        ref1 = _make_batch_ref(batch_index=0, event_count=4)
        t.evict_events(
            batch_ref=ref1,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=3.0,
        )
        assert len(t.events) == 6
        assert len(t.journal_refs) == 1

        # Second eviction: cutoff=7 → removes ws 4,5,6,7 (4 events)
        ref2 = _make_batch_ref(batch_index=1, event_count=4)
        t.evict_events(
            batch_ref=ref2,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=7.0,
        )
        assert len(t.events) == 2
        assert len(t.journal_refs) == 2
        assert t.journal_refs[0] is ref1
        assert t.journal_refs[1] is ref2

    def test_events_property_returns_non_evicted(self) -> None:
        """transcript.events returns only non-evicted events."""
        events: list[Event] = [
            _make_logger_event(working_start=0.0),
            _make_logger_event(working_start=1.0),
            _make_model_event(working_start=2.0),
        ]
        t = Transcript(events=list(events))

        batch_ref = _make_batch_ref(event_count=2)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=1.0,
        )

        remaining = list(t.events)
        assert len(remaining) == 1
        assert isinstance(remaining[0], ModelEvent)

    def test_evict_with_interleaved_events(self) -> None:
        """LoggerEvent-ModelEvent-LoggerEvent-ModelEvent: only eligible LoggerEvents removed."""
        events: list[Event] = [
            _make_logger_event(working_start=0.0),
            _make_model_event(working_start=1.0),
            _make_logger_event(working_start=2.0),
            _make_model_event(working_start=3.0),
        ]
        t = Transcript(events=list(events))

        batch_ref = _make_batch_ref(event_count=2)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=5.0,
        )

        remaining = list(t.events)
        assert len(remaining) == 2
        assert all(isinstance(e, ModelEvent) for e in remaining)

    def test_evict_respects_working_start_boundary(self) -> None:
        """Events after the cutoff stay even if they are evictable types."""
        events: list[Event] = [
            _make_logger_event(working_start=1.0),
            _make_logger_event(working_start=5.0),
            _make_logger_event(working_start=10.0),
            _make_info_event(working_start=2.0),
            _make_info_event(working_start=8.0),
        ]
        t = Transcript(events=list(events))

        batch_ref = _make_batch_ref(event_count=2)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=4.0,
        )

        remaining = list(t.events)
        # ws=1.0 (Logger) and ws=2.0 (Info) evicted; ws=5.0, ws=10.0, ws=8.0 stay
        assert len(remaining) == 3
        for e in remaining:
            assert e.working_start > 4.0

    def test_evict_zero_events_does_not_append_ref(self) -> None:
        """If 0 events matched, _journal_refs should NOT get a new entry."""
        # All events are beyond cutoff
        events = [
            _make_logger_event(working_start=10.0),
            _make_logger_event(working_start=20.0),
        ]
        t = Transcript(events=list(events))

        batch_ref = _make_batch_ref(event_count=0)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=5.0,
        )

        assert len(t.events) == 2
        assert len(t.journal_refs) == 0

    def test_evict_preserves_tool_events(self) -> None:
        """ToolEvent is NOT in default evictable types and must survive eviction (DEC-003)."""
        tool_event = ToolEvent(
            type="function",
            id="call-1",
            function="test_tool",
            arguments={},
            result="ok",
            working_start=1.0,
            timestamp=datetime.now(tz=timezone.utc),
        )
        events: list[Event] = [
            _make_logger_event(working_start=0.0),
            tool_event,
            _make_logger_event(working_start=2.0),
        ]
        t = Transcript(events=list(events))

        batch_ref = _make_batch_ref(event_count=2)
        t.evict_events(
            batch_ref=batch_ref,
            evictable_types=EVICTABLE_TYPES,
            max_working_start=10.0,
        )

        remaining = list(t.events)
        assert len(remaining) == 1
        assert isinstance(remaining[0], ToolEvent)
