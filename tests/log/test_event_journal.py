"""Tests for EventJournal batch writing and reading (Phase 1).

Covers Tasks 1 from the incremental journaling plan:
- Accumulation, threshold signaling, queue management
- Flush pending, flush all, read batches
- Config validation, boundary values
- Per-sample signal isolation (DEC-013)
- Non-evictable event skipping (DEC-016)
- Write failure handling
- Background flush loop
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from pydantic import ValidationError

from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._recorders.journal import (
    EventJournal,
    EventJournalConfig,
    JournalBatchRef,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logger_event(working_start: float = 0.0) -> LoggerEvent:
    """Create a minimal LoggerEvent for testing."""
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
    """Create a minimal InfoEvent for testing."""
    return InfoEvent(
        data="test-data",
        working_start=working_start,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_model_event(working_start: float = 0.0) -> ModelEvent:
    """Create a minimal ModelEvent for testing."""
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


def _make_zip_log_mock() -> MagicMock:
    """Create a mock ZipLogFile with the required async methods."""
    mock = MagicMock()
    mock.write = AsyncMock()
    mock.read_entry = AsyncMock(return_value=b"[]")
    mock.namelist = AsyncMock(return_value=[])
    return mock


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------


class TestEventJournalConfig:
    def test_journal_config_validation(self) -> None:
        """batch_size < 1 rejected, batch_size > 1000 rejected (DEC-015)."""
        with pytest.raises(ValidationError):
            EventJournalConfig(batch_size=0)
        with pytest.raises(ValidationError):
            EventJournalConfig(batch_size=-1)
        with pytest.raises(ValidationError):
            EventJournalConfig(batch_size=1001)

    def test_journal_config_boundary_values(self) -> None:
        """batch_size=1 and batch_size=1000 accepted."""
        config_min = EventJournalConfig(batch_size=1)
        assert config_min.batch_size == 1

        config_max = EventJournalConfig(batch_size=1000)
        assert config_max.batch_size == 1000

    def test_journal_config_defaults(self) -> None:
        """Default config has batch_size=100 and evicts LoggerEvent + InfoEvent."""
        config = EventJournalConfig()
        assert config.batch_size == 100
        assert config.evict_after_write is True
        assert LoggerEvent in config.evictable_event_types
        assert InfoEvent in config.evictable_event_types

    def test_journal_config_frozen(self) -> None:
        """Config is immutable."""
        config = EventJournalConfig()
        with pytest.raises(ValidationError):
            config.batch_size = 50  # type: ignore[misc]


class TestJournalBatchRef:
    def test_journal_batch_ref_frozen(self) -> None:
        """JournalBatchRef is immutable."""
        ref = JournalBatchRef(
            batch_index=0, event_count=10, sample_id="s1", epoch=1
        )
        assert ref.batch_index == 0
        assert ref.event_count == 10
        assert ref.sample_id == "s1"
        assert ref.epoch == 1
        with pytest.raises(ValidationError):
            ref.batch_index = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Accumulation and threshold tests
# ---------------------------------------------------------------------------


class TestEventJournalAccumulation:
    def test_journal_accumulates_events_below_threshold(self) -> None:
        """Adding 50 events (batch_size=100) does NOT trigger a batch."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        for i in range(50):
            result = journal.add_event("sample1", 1, _make_logger_event(float(i)))

        assert journal.pending_count("sample1", 1) == 50
        assert not journal.has_pending_batches("sample1", 1)
        # No batch was triggered
        assert result is False

    def test_journal_signals_at_threshold(self) -> None:
        """Adding 100 events causes add_event() to return True and enqueue a batch."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        triggered = False
        for i in range(100):
            if journal.add_event("sample1", 1, _make_logger_event(float(i))):
                triggered = True

        assert triggered
        assert journal.has_pending_batches("sample1", 1)
        # Buffer should be empty after batch promotion
        assert journal.pending_count("sample1", 1) == 0

    def test_journal_multiple_batches_queue(self) -> None:
        """Adding 250 events enqueues 2 batches + 50 still in buffer (DEC-009)."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        trigger_count = 0
        for i in range(250):
            if journal.add_event("sample1", 1, _make_logger_event(float(i))):
                trigger_count += 1

        assert trigger_count == 2
        assert journal.pending_count("sample1", 1) == 50
        assert journal.has_pending_batches("sample1", 1)

    def test_journal_skips_non_evictable_events(self) -> None:
        """Adding ModelEvent does NOT buffer it; pending_count stays 0 (DEC-016)."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        result = journal.add_event("sample1", 1, _make_model_event(0.0))
        assert result is False
        assert journal.pending_count("sample1", 1) == 0


# ---------------------------------------------------------------------------
# Flush tests
# ---------------------------------------------------------------------------


class TestEventJournalFlush:
    async def test_journal_flush_pending_writes_all_queued(self) -> None:
        """Enqueue 3 batches, call flush_pending_batches(), verify all 3 written."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=10)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Add 30 events → 3 batches
        for i in range(30):
            journal.add_event("s1", 1, _make_logger_event(float(i)))

        assert journal.has_pending_batches("s1", 1)

        batches_written = await journal.flush_pending_batches("s1", 1)
        assert batches_written == 3
        assert not journal.has_pending_batches("s1", 1)

        # Verify write was called 3 times with correct paths
        assert zip_log.write.call_count == 3
        paths = [call.args[0] for call in zip_log.write.call_args_list]
        assert paths == [
            "_journal/events/s1_epoch_1/batch_0.json",
            "_journal/events/s1_epoch_1/batch_1.json",
            "_journal/events/s1_epoch_1/batch_2.json",
        ]

    async def test_journal_flush_all_writes_remaining(self) -> None:
        """flush_all() writes queued batches + buffer remainder."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=10)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Add 25 events → 2 full batches + 5 in buffer
        for i in range(25):
            journal.add_event("s1", 1, _make_logger_event(float(i)))

        batches_written = await journal.flush_all("s1", 1)
        assert batches_written == 3  # 2 queued + 1 remainder
        assert journal.pending_count("s1", 1) == 0
        assert not journal.has_pending_batches("s1", 1)

        # Verify 3 writes total
        assert zip_log.write.call_count == 3

    def test_journal_batch_path_format(self) -> None:
        """Verify path is _journal/events/{sample_id}_epoch_{epoch}/batch_{N}.json."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=1)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Trigger a single batch with batch_size=1
        journal.add_event("my_sample", 2, _make_logger_event(0.0))

        # Check the pending queue has the right batch_index
        key = ("my_sample", 2)
        queue = journal._pending_queue[key]
        batch_index, _max_ws, _events = queue[0]
        expected_path = f"_journal/events/my_sample_epoch_2/batch_{batch_index}.json"
        assert expected_path == "_journal/events/my_sample_epoch_2/batch_0.json"

    async def test_journal_flush_pending_no_batches(self) -> None:
        """flush_pending_batches returns 0 when nothing is queued."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        batches_written = await journal.flush_pending_batches("s1", 1)
        assert batches_written == 0


# ---------------------------------------------------------------------------
# Read batches tests
# ---------------------------------------------------------------------------


class TestEventJournalReadBatches:
    async def test_journal_read_batches_returns_events_in_order(self) -> None:
        """Read back written batches, verify event ordering by (working_start, timestamp)."""
        from inspect_ai._util.json import to_json_safe

        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=5)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Create events with specific working_start values
        events_batch1 = [_make_logger_event(float(i)) for i in [5, 3, 1]]
        events_batch2 = [_make_logger_event(float(i)) for i in [4, 2, 0]]

        # Serialize the events the same way ZipLogFile.write would
        batch1_json = to_json_safe(events_batch1, indent=None)
        batch2_json = to_json_safe(events_batch2, indent=None)

        # Mock namelist to return batch file names
        zip_log.namelist = AsyncMock(return_value=[
            "_journal/events/s1_epoch_1/batch_0.json",
            "_journal/events/s1_epoch_1/batch_1.json",
        ])

        # Mock read_entry to return serialized events
        async def mock_read_entry(name: str) -> bytes:
            if "batch_0" in name:
                return batch1_json
            elif "batch_1" in name:
                return batch2_json
            return b"[]"

        zip_log.read_entry = AsyncMock(side_effect=mock_read_entry)

        result = await journal.read_batches("s1", 1)
        assert len(result) == 6

        # Should be sorted by working_start
        working_starts = [e.working_start for e in result]
        assert working_starts == sorted(working_starts)

    async def test_journal_read_empty_returns_empty_list(self) -> None:
        """No batches written → empty list returned."""
        zip_log = _make_zip_log_mock()
        zip_log.namelist = AsyncMock(return_value=[])
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        result = await journal.read_batches("s1", 1)
        assert result == []

    async def test_journal_serializes_all_event_types(self) -> None:
        """LoggerEvent, InfoEvent round-trip through JSON serialization."""
        from inspect_ai._util.json import to_json_safe
        from inspect_ai.log._condense import _events_adapter

        events: list[Event] = [
            _make_logger_event(1.0),
            _make_info_event(2.0),
        ]

        # Serialize and deserialize
        serialized = to_json_safe(events, indent=None)
        deserialized = _events_adapter().validate_json(serialized)

        assert len(deserialized) == 2
        assert isinstance(deserialized[0], LoggerEvent)
        assert isinstance(deserialized[1], InfoEvent)


# ---------------------------------------------------------------------------
# Per-sample signal isolation tests (DEC-013)
# ---------------------------------------------------------------------------


class TestFlushSignalIsolation:
    async def test_flush_signal_per_sample_isolation(self) -> None:
        """Two samples registered; sample A hits threshold → only A's signal is set."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=5)
        journal = EventJournal(zip_log=zip_log, config=config)

        journal.register_sample("sA", 1)
        journal.register_sample("sB", 1)

        # Add 5 events to sample A (hits threshold)
        for i in range(5):
            journal.add_event("sA", 1, _make_logger_event(float(i)))

        # Sample A's signal should be set
        signal_a = journal._flush_signals[("sA", 1)]
        assert signal_a.is_set()

        # Sample B's signal should NOT be set
        signal_b = journal._flush_signals[("sB", 1)]
        assert not signal_b.is_set()

    def test_register_and_unregister_sample(self) -> None:
        """register_sample creates signal, unregister cleans up."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        journal.register_sample("s1", 1)
        assert ("s1", 1) in journal._flush_signals

        journal.unregister_sample("s1", 1)
        assert ("s1", 1) not in journal._flush_signals

    def test_unregister_cleans_up_buffers(self) -> None:
        """unregister_sample also cleans up _buffers, _batch_counters, _pending_queue."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        journal.register_sample("s1", 1)
        # Add some events to create buffer entries
        for i in range(5):
            journal.add_event("s1", 1, _make_logger_event(float(i)))

        assert ("s1", 1) in journal._buffers

        journal.unregister_sample("s1", 1)
        assert ("s1", 1) not in journal._buffers
        assert ("s1", 1) not in journal._batch_counters
        assert ("s1", 1) not in journal._pending_queue
        assert ("s1", 1) not in journal._flush_signals


# ---------------------------------------------------------------------------
# Write failure tests
# ---------------------------------------------------------------------------


class TestEventJournalWriteFailure:
    async def test_journal_write_failure_preserves_events(self) -> None:
        """Mock write() to raise; batch stays in deque for retry."""
        zip_log = _make_zip_log_mock()
        zip_log.write = AsyncMock(side_effect=IOError("disk full"))
        config = EventJournalConfig(batch_size=5)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Add 5 events to create a batch
        for i in range(5):
            journal.add_event("s1", 1, _make_logger_event(float(i)))

        assert journal.has_pending_batches("s1", 1)

        # Flush should fail but not lose the batch
        batches_written = await journal.flush_pending_batches("s1", 1)
        assert batches_written == 0
        assert journal.has_pending_batches("s1", 1)  # Still there

    async def test_journal_write_failure_stops_at_first_error(self) -> None:
        """3 batches queued, 2nd write fails → 1st written, 2nd+3rd remain."""
        zip_log = _make_zip_log_mock()
        call_count = 0

        async def write_with_failure(path: str, data: list[Event]) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise IOError("write error")

        zip_log.write = AsyncMock(side_effect=write_with_failure)
        config = EventJournalConfig(batch_size=5)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Add 15 events → 3 batches
        for i in range(15):
            journal.add_event("s1", 1, _make_logger_event(float(i)))

        batches_written = await journal.flush_pending_batches("s1", 1)
        assert batches_written == 1  # Only the first succeeded

        # 2 batches should remain in queue
        key = ("s1", 1)
        assert len(journal._pending_queue[key]) == 2

    async def test_journal_flush_all_write_failure_restores_buffer(self) -> None:
        """flush_all restores buffer on write failure for remainder batch."""
        zip_log = _make_zip_log_mock()
        zip_log.write = AsyncMock(side_effect=IOError("write error"))
        config = EventJournalConfig(batch_size=100)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Add 5 events (below threshold, so only in buffer)
        for i in range(5):
            journal.add_event("s1", 1, _make_logger_event(float(i)))

        batches_written = await journal.flush_all("s1", 1)
        assert batches_written == 0
        # Buffer should be restored
        assert journal.pending_count("s1", 1) == 5


# ---------------------------------------------------------------------------
# Background flush loop test
# ---------------------------------------------------------------------------


class TestEventJournalBackgroundFlush:
    async def test_journal_background_flush_loop(self) -> None:
        """Verify run_background_flush awaits signal, flushes, resets, loops."""
        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=5)
        journal = EventJournal(zip_log=zip_log, config=config)

        journal.register_sample("s1", 1)

        flush_count = 0
        original_flush = journal.flush_pending_batches

        async def counting_flush(
            sample_id: str | int,
            epoch: int,
            transcript: object = None,
            evictable_types: object = None,
        ) -> int:
            nonlocal flush_count
            result = await original_flush(
                sample_id, epoch, transcript, evictable_types
            )
            flush_count += 1
            return result

        journal.flush_pending_batches = counting_flush  # type: ignore[assignment]

        async with anyio.create_task_group() as tg:
            tg.start_soon(journal.run_background_flush, "s1", 1, None, None)

            # Add events to trigger a batch
            for i in range(5):
                journal.add_event("s1", 1, _make_logger_event(float(i)))

            # Give the background task time to process
            await anyio.sleep(0.1)

            # Should have flushed at least once
            assert flush_count >= 1

            # Signal should have been reset — add another batch
            for i in range(5):
                journal.add_event("s1", 1, _make_logger_event(float(i + 5)))

            await anyio.sleep(0.1)
            assert flush_count >= 2

            # Unregister to stop the loop
            journal.unregister_sample("s1", 1)
            # Give loop time to exit
            await anyio.sleep(0.1)
            tg.cancel_scope.cancel()


class TestFlushEvictsFromTranscript:
    """Integration test: flush→evict path produces disjoint sets (DEC-016 + DEC-010)."""

    @pytest.mark.anyio
    async def test_flush_pending_evicts_from_transcript(self) -> None:
        """After flush_pending_batches with transcript, evictable events are removed."""
        from inspect_ai.event._model import ModelEvent
        from inspect_ai.log._transcript import Transcript
        from inspect_ai.model._generate_config import GenerateConfig
        from inspect_ai.model._model_output import ModelOutput

        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=3)
        journal = EventJournal(zip_log=zip_log, config=config)

        # Create transcript with mixed events
        logger_events = [_make_logger_event(float(i)) for i in range(3)]
        model_event = ModelEvent(
            model="test",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_content("test", "hi"),
            working_start=1.5,
            timestamp=logger_events[0].timestamp,
        )
        all_events = list(logger_events) + [model_event]
        transcript = Transcript(events=list(all_events))
        assert len(transcript.events) == 4

        # Add 3 logger events → triggers batch
        for evt in logger_events:
            journal.add_event("s1", 1, evt)

        # The model event is NOT added (DEC-016: non-evictable skipped)
        journal.add_event("s1", 1, model_event)

        evictable_types = (LoggerEvent, InfoEvent)

        # Flush with transcript → should evict logger events
        written = await journal.flush_pending_batches(
            "s1", 1, transcript, evictable_types
        )
        assert written == 1

        # Transcript should only have the model event left
        remaining = list(transcript.events)
        assert len(remaining) == 1
        assert isinstance(remaining[0], ModelEvent)

        # Journal refs should be tracked
        assert len(transcript.journal_refs) == 1

    @pytest.mark.anyio
    async def test_flush_all_evicts_from_transcript(self) -> None:
        """flush_all with transcript evicts both queued batches and final buffer."""
        from inspect_ai.log._transcript import Transcript

        zip_log = _make_zip_log_mock()
        config = EventJournalConfig(batch_size=2)
        journal = EventJournal(zip_log=zip_log, config=config)

        events = [_make_logger_event(float(i)) for i in range(5)]
        transcript = Transcript(events=list(events))
        assert len(transcript.events) == 5

        # Add 5 events: 2 batches of 2 + 1 remaining in buffer
        for evt in events:
            journal.add_event("s1", 1, evt)

        evictable_types = (LoggerEvent, InfoEvent)

        written = await journal.flush_all("s1", 1, transcript, evictable_types)
        assert written == 3  # 2 queued batches + 1 final buffer batch

        # All logger events should be evicted
        remaining = list(transcript.events)
        assert len(remaining) == 0

        # Journal refs tracked for each eviction that actually removed events
        assert len(transcript.journal_refs) == 3
