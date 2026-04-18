"""Incremental event journaling for eval ZIP files.

Manages batched writing of events to ``_journal/events/`` entries inside
the ``.eval`` ZIP archive during sample execution, and reading them back
for reconstruction at sample completion.

Architecture (DEC-007):
- Sync methods (safe from ``on_sample_event`` callback):
  ``add_event()``, ``pending_count()``, ``has_pending_batches()``
- Async methods (called from background flush task or sample completion):
  ``flush_pending_batches()``, ``flush_all()``, ``read_batches()``,
  ``run_background_flush()``
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

import anyio
from pydantic import BaseModel, ConfigDict, Field

from inspect_ai.event._base import BaseEvent
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._logger import LoggerEvent
from inspect_ai.log._condense import _events_adapter

if TYPE_CHECKING:
    from inspect_ai.event._event import Event
    from inspect_ai.log._recorders.eval import ZipLogFile
    from inspect_ai.log._transcript import Transcript

logger = logging.getLogger(__name__)


class JournalBatchRef(BaseModel):
    """Metadata tracking a batch of events written to journal."""

    model_config = ConfigDict(frozen=True)

    batch_index: int
    """Batch number within this sample's journal."""

    event_count: int
    """Number of events in this batch."""

    sample_id: str | int
    """Sample ID this batch belongs to."""

    epoch: int
    """Epoch this batch belongs to."""


class EventJournalConfig(BaseModel):
    """Configuration for incremental event journaling."""

    model_config = ConfigDict(frozen=True)

    batch_size: int = Field(default=100, ge=1, le=1000)
    """Number of events to buffer before writing a journal batch.

    Values <10 are for testing only.
    """

    evict_after_write: bool = Field(default=True)
    """Whether to evict eligible events from memory after journaling."""

    evictable_event_types: tuple[type[BaseEvent], ...] = Field(
        default=(LoggerEvent, InfoEvent)
    )
    """Event types eligible for eviction from in-memory Transcript.

    Uses ``isinstance()`` matching.
    """


class EventJournal:
    """Manages incremental event writing to ZIP journal entries.

    Pending batches are stored in a deque per sample (DEC-009) to prevent
    data loss when multiple batches accumulate before the flush task runs.
    """

    def __init__(
        self,
        zip_log: ZipLogFile,
        config: EventJournalConfig,
    ) -> None:
        self._zip_log = zip_log
        self._config = config
        # Per-sample buffers for events not yet promoted to a batch
        self._buffers: dict[tuple[str | int, int], list[Event]] = {}
        # Per-sample batch counter for path generation
        self._batch_counters: dict[tuple[str | int, int], int] = {}
        # Per-sample queue of (batch_index, max_working_start, events)
        self._pending_queue: dict[
            tuple[str | int, int],
            deque[tuple[int, float, list[Event]]],
        ] = {}
        # Per-sample flush signals (DEC-013)
        self._flush_signals: dict[tuple[str | int, int], anyio.Event] = {}

    @property
    def config(self) -> EventJournalConfig:
        """Journal configuration."""
        return self._config

    # --- SYNC methods (called from on_sample_event) ---

    def add_event(
        self,
        sample_id: str | int,
        epoch: int,
        event: Event,
    ) -> bool:
        """Add event to buffer. Returns True if a new batch is ready for flushing.

        Only buffers events matching ``evictable_event_types`` (DEC-016).
        Non-evictable events are skipped — they stay exclusively in memory.
        """
        if not isinstance(event, self._config.evictable_event_types):
            return False

        key = (sample_id, epoch)
        buf = self._buffers.setdefault(key, [])
        buf.append(event)

        if len(buf) >= self._config.batch_size:
            batch_index = self._batch_counters.get(key, 0)
            max_working_start = max(e.working_start for e in buf)

            queue = self._pending_queue.setdefault(key, deque())
            queue.append((batch_index, max_working_start, list(buf)))
            buf.clear()
            self._batch_counters[key] = batch_index + 1

            signal = self._flush_signals.get(key)
            if signal is not None:
                signal.set()
            return True
        return False

    def pending_count(self, sample_id: str | int, epoch: int) -> int:
        """Number of events in buffer (not yet promoted to a batch)."""
        return len(self._buffers.get((sample_id, epoch), []))

    def has_pending_batches(self, sample_id: str | int, epoch: int) -> bool:
        """Whether there are batches queued for async write."""
        return bool(self._pending_queue.get((sample_id, epoch)))

    # --- Per-sample signal lifecycle (DEC-013) ---

    def register_sample(self, sample_id: str | int, epoch: int) -> None:
        """Register a sample's flush signal. Call before starting background flush."""
        self._flush_signals[(sample_id, epoch)] = anyio.Event()

    def unregister_sample(self, sample_id: str | int, epoch: int) -> None:
        """Unregister a sample and clean up all associated state."""
        key = (sample_id, epoch)
        self._flush_signals.pop(key, None)
        self._buffers.pop(key, None)
        self._batch_counters.pop(key, None)
        self._pending_queue.pop(key, None)

    # --- ASYNC methods ---

    async def flush_pending_batches(
        self,
        sample_id: str | int,
        epoch: int,
        transcript: Transcript | None = None,
        evictable_types: tuple[type[BaseEvent], ...] | None = None,
    ) -> int:
        """Write all queued batches to ZIP. Returns number of batches written.

        After each successful write, evicts matching events from transcript (DEC-010).
        On write failure, remaining batches stay in queue for retry.
        """
        key = (sample_id, epoch)
        queue = self._pending_queue.get(key)
        if not queue:
            return 0

        batches_written = 0
        while queue:
            batch_index, max_working_start, events = queue[0]
            path = (
                f"_journal/events/{sample_id}_epoch_{epoch}"
                f"/batch_{batch_index}.json"
            )
            try:
                await self._zip_log.write(path, events)
            except Exception:
                logger.warning(
                    "Journal batch write failed for %s", path, exc_info=True
                )
                break
            queue.popleft()
            batches_written += 1

            # Evict matching events from transcript (DEC-010)
            if transcript is not None and evictable_types is not None:
                ref = JournalBatchRef(
                    batch_index=batch_index,
                    event_count=len(events),
                    sample_id=sample_id,
                    epoch=epoch,
                )
                transcript.evict_events(ref, evictable_types, max_working_start)

        return batches_written

    async def flush_all(
        self,
        sample_id: str | int,
        epoch: int,
        transcript: Transcript | None = None,
        evictable_types: tuple[type[BaseEvent], ...] | None = None,
    ) -> int:
        """Write ALL remaining events (queued batches + buffer) to ZIP.

        Called at sample completion before reconstruction.
        Must be called only after the solver has completed —
        no concurrent ``add_event()`` calls may occur during this method.

        Returns:
            Total number of batches written.
        """
        key = (sample_id, epoch)

        batches_written = await self.flush_pending_batches(
            sample_id, epoch, transcript, evictable_types
        )

        buf = self._buffers.pop(key, [])
        if buf:
            batch_index = self._batch_counters.get(key, 0)
            path = (
                f"_journal/events/{sample_id}_epoch_{epoch}"
                f"/batch_{batch_index}.json"
            )
            try:
                await self._zip_log.write(path, buf)
                self._batch_counters[key] = batch_index + 1
                batches_written += 1

                # Evict matching events from transcript (DEC-010)
                if transcript is not None and evictable_types is not None:
                    max_working_start = max(e.working_start for e in buf)
                    ref = JournalBatchRef(
                        batch_index=batch_index,
                        event_count=len(buf),
                        sample_id=sample_id,
                        epoch=epoch,
                    )
                    transcript.evict_events(
                        ref, evictable_types, max_working_start
                    )
            except Exception:
                logger.warning(
                    "Journal final batch write failed for %s", path, exc_info=True
                )
                self._buffers[key] = buf

        return batches_written

    async def read_batches(
        self,
        sample_id: str | int,
        epoch: int,
    ) -> list[Event]:
        """Read all journaled events for a sample from ZIP, in order.

        Enumerates ZIP entries matching
        ``_journal/events/{sample_id}_epoch_{epoch}/batch_*.json``,
        deserializes each batch, and returns all events sorted by
        ``(working_start, timestamp)``.
        """
        prefix = f"_journal/events/{sample_id}_epoch_{epoch}/"

        entry_names = await self._zip_log.namelist()
        if not entry_names:
            return []

        batch_entries = sorted(
            name
            for name in entry_names
            if name.startswith(prefix) and name.endswith(".json")
        )

        all_events: list[Event] = []
        for entry_name in batch_entries:
            raw = await self._zip_log.read_entry(entry_name)
            batch_events = _events_adapter().validate_json(raw)
            all_events.extend(batch_events)

        all_events.sort(key=lambda e: (e.working_start, e.timestamp))
        return all_events

    async def run_background_flush(
        self,
        sample_id: str | int,
        epoch: int,
        transcript: Transcript | None = None,
        evictable_types: tuple[type[BaseEvent], ...] | None = None,
    ) -> None:
        """Background flush loop — runs in sample's TaskGroup.

        Waits for this sample's ``flush_signal`` (DEC-013), then writes all
        pending batches. Continues until the sample is unregistered or the
        task group is cancelled.
        """
        key = (sample_id, epoch)
        while True:
            signal = self._flush_signals.get(key)
            if signal is None:
                return
            await signal.wait()
            # Reset signal for next batch trigger
            self._flush_signals[key] = anyio.Event()
            try:
                await self.flush_pending_batches(
                    sample_id, epoch, transcript, evictable_types
                )
            except Exception:
                logger.warning(
                    "Background journal flush failed for sample=%s epoch=%d",
                    sample_id,
                    epoch,
                    exc_info=True,
                )
