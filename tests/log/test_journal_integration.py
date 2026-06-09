"""Tests for Phase 3: TaskLogger journal wiring, EvalConfig fields, and run.py integration.

Covers Tasks 5-8 from the incremental journaling plan:
- EvalConfig journal fields (Task 8.1)
- TaskLogger journal support (Tasks 5-6)
- create_eval_sample events parameter (Task 8.5)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from inspect_ai.dataset import Sample
from inspect_ai.event._event import Event
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.log._log import EvalConfig
from inspect_ai.log._recorders.journal import EventJournal, EventJournalConfig
from inspect_ai.model import ModelName
from inspect_ai.scorer import Score, Target
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.solver import TaskState

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


# ---------------------------------------------------------------------------
# Part A: EvalConfig journal fields (Task 8.1)
# ---------------------------------------------------------------------------


class TestEvalConfigJournalFields:
    """Test new journal fields on EvalConfig."""

    def test_eval_config_journal_fields_default_none(self) -> None:
        """New fields default to None (DEC-006: opt-in)."""
        config = EvalConfig()
        assert config.log_journal_events is None
        assert config.journal_batch_size is None

    def test_eval_config_log_journal_events_true(self) -> None:
        """log_journal_events can be set to True."""
        config = EvalConfig(log_journal_events=True)
        assert config.log_journal_events is True

    def test_eval_config_log_journal_events_false(self) -> None:
        """log_journal_events can be set to False."""
        config = EvalConfig(log_journal_events=False)
        assert config.log_journal_events is False

    def test_eval_config_journal_batch_size(self) -> None:
        """journal_batch_size can be set to an integer."""
        config = EvalConfig(journal_batch_size=50)
        assert config.journal_batch_size == 50

    def test_eval_config_serialization_round_trip(self) -> None:
        """Journal fields survive JSON serialization round-trip."""
        config = EvalConfig(log_journal_events=True, journal_batch_size=200)
        data = config.model_dump()
        restored = EvalConfig(**data)
        assert restored.log_journal_events is True
        assert restored.journal_batch_size == 200


# ---------------------------------------------------------------------------
# Part B: TaskLogger journal support (Tasks 5-6)
# ---------------------------------------------------------------------------


class TestTaskLoggerJournal:
    """Test TaskLogger journal integration."""

    def _make_mock_task_logger(
        self,
        *,
        recorder_is_eval: bool = True,
    ) -> MagicMock:
        """Create a mock TaskLogger with the attributes needed for journal tests."""
        logger = MagicMock()
        logger._journal = None

        if recorder_is_eval:
            # Mock EvalRecorder with get_zip_log
            mock_zip_log = MagicMock()
            logger.recorder = MagicMock()
            logger.recorder.get_zip_log.return_value = mock_zip_log
            # Make isinstance check work for EvalRecorder
            logger.recorder.__class__ = MagicMock
        else:
            logger.recorder = MagicMock()

        logger.eval = MagicMock()
        return logger

    def test_task_logger_creates_journal_when_enabled(self) -> None:
        """When log_journal_events=True, TaskLogger.init_journal creates an EventJournal."""
        from inspect_ai._eval.task.log import TaskLogger
        from inspect_ai.log._recorders.eval import EvalRecorder

        # Create a mock recorder that IS an EvalRecorder
        mock_zip_log = MagicMock()
        mock_recorder = MagicMock(spec=EvalRecorder)
        mock_recorder.get_zip_log.return_value = mock_zip_log

        # Create a minimal TaskLogger-like object to test init_journal
        # We'll test the actual method by calling it on a real-ish object
        task_logger = MagicMock(spec=TaskLogger)
        task_logger.recorder = mock_recorder
        task_logger.eval = MagicMock()
        task_logger._journal = None

        # Call the real init_journal method
        config = EventJournalConfig(batch_size=50)
        TaskLogger.init_journal(task_logger, config)

        assert task_logger._journal is not None
        assert isinstance(task_logger._journal, EventJournal)
        mock_recorder.get_zip_log.assert_called_once_with(task_logger.eval)

    def test_task_logger_no_journal_by_default(self) -> None:
        """When log_journal_events is None/False, no journal is created."""
        from inspect_ai._eval.task.log import TaskLogger

        # Create a mock with _journal = None
        task_logger = object.__new__(TaskLogger)
        task_logger._journal = None

        # journal property should return None
        assert task_logger.journal is None

    def test_task_logger_init_journal_non_eval_recorder(self) -> None:
        """init_journal is a no-op when recorder is not an EvalRecorder."""
        from inspect_ai._eval.task.log import TaskLogger
        from inspect_ai.log._recorders.recorder import Recorder

        mock_recorder = MagicMock(spec=Recorder)

        task_logger = MagicMock(spec=TaskLogger)
        task_logger.recorder = mock_recorder
        task_logger.eval = MagicMock()
        task_logger._journal = None

        config = EventJournalConfig(batch_size=50)
        TaskLogger.init_journal(task_logger, config)

        # Journal should still be None since recorder is not EvalRecorder
        assert task_logger._journal is None

    def test_task_logger_journal_property(self) -> None:
        """Journal property returns the EventJournal when set."""
        from inspect_ai._eval.task.log import TaskLogger

        mock_journal = MagicMock(spec=EventJournal)
        task_logger = object.__new__(TaskLogger)
        task_logger._journal = mock_journal

        result = task_logger.journal
        assert result is mock_journal


# ---------------------------------------------------------------------------
# Part D: create_eval_sample events parameter (Task 8.5)
# ---------------------------------------------------------------------------


class TestCreateEvalSampleEvents:
    """Test that create_eval_sample uses provided events parameter."""

    def _make_sample_and_state(
        self,
    ) -> tuple[Sample, TaskState, dict[str, SampleScore]]:
        """Create minimal Sample and TaskState for create_eval_sample."""
        sample = Sample(
            input="test input",
            target="test target",
            id="test-1",
        )
        state = TaskState(
            sample_id="test-1",
            epoch=1,
            model=ModelName("test/model"),
            input="test input",
            target=Target("test target"),
            messages=[],
            completed=True,
        )
        scores = {
            "accuracy": SampleScore(
                score=Score(value=1.0),
                sample_id="test-1",
            )
        }
        return sample, state, scores

    def test_create_eval_sample_uses_provided_events(self) -> None:
        """When events parameter is given, uses it instead of transcript().events."""
        from inspect_ai._eval.task.run import create_eval_sample

        sample, state, scores = self._make_sample_and_state()
        custom_events: list[Event] = [
            _make_logger_event(1.0),
            _make_logger_event(2.0),
        ]

        # Patch transcript to return something different to verify we DON'T use it
        with patch("inspect_ai._eval.task.run.transcript") as mock_transcript:
            mock_transcript_obj = MagicMock()
            mock_transcript_obj.events = [_make_logger_event(99.0)]
            mock_transcript_obj.timelines = []
            mock_transcript_obj.attachments = {}
            mock_transcript.return_value = mock_transcript_obj

            eval_sample = create_eval_sample(
                start_time=None,
                sample=sample,
                state=state,
                scores=scores,
                error=None,
                limit=None,
                error_retries=[],
                events=custom_events,
            )

        assert eval_sample.events == custom_events
        assert len(eval_sample.events) == 2

    def test_create_eval_sample_default_uses_transcript(self) -> None:
        """When events is None, falls back to list(transcript().events)."""
        from inspect_ai._eval.task.run import create_eval_sample

        sample, state, scores = self._make_sample_and_state()
        transcript_events = [_make_logger_event(5.0), _make_logger_event(6.0)]

        with patch("inspect_ai._eval.task.run.transcript") as mock_transcript:
            mock_transcript_obj = MagicMock()
            mock_transcript_obj.events = transcript_events
            mock_transcript_obj.timelines = []
            mock_transcript_obj.attachments = {}
            mock_transcript.return_value = mock_transcript_obj

            eval_sample = create_eval_sample(
                start_time=None,
                sample=sample,
                state=state,
                scores=scores,
                error=None,
                limit=None,
                error_retries=[],
            )

        assert eval_sample.events == transcript_events
