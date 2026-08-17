"""Auto-Extraction Queue Management.

Manages batching and flushing of messages for KG extraction.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractionBatch:
    """A batch of messages pending extraction for a workspace."""
    workspace_name: str
    message_ids: list[str] = field(default_factory=list)
    session_names: set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ExtractionQueue:
    """Manages batching and flushing of messages for KG extraction.

    Batches messages by workspace, flushes on size or time thresholds.
    Runs extraction in background without blocking message ingestion.
    """

    def __init__(self):
        self._batches: dict[str, ExtractionBatch] = {}
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._shutdown = False

        # Config
        self.batch_size = getattr(settings, "EXTRACTION_BATCH_SIZE", 50)
        self.flush_interval = getattr(settings, "EXTRACTION_FLUSH_INTERVAL", 30.0)
        self.max_concurrent = getattr(settings, "EXTRACTION_MAX_CONCURRENT", 2)

    async def start(self):
        """Start the background flush task."""
        if self._flush_task is None:
            self._shutdown = False
            self._flush_task = asyncio.create_task(self._flush_loop())
            logger.info("Extraction queue started")

    async def stop(self):
        """Stop the flush task and flush remaining batches."""
        self._shutdown = True
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush
        await self.flush_all()
        logger.info("Extraction queue stopped")

    async def enqueue(
        self,
        workspace_name: str,
        message_ids: list[str],
        session_name: str | None = None,
    ):
        """Add message IDs to the extraction queue for a workspace."""
        async with self._lock:
            batch = self._batches.get(workspace_name)
            if batch is None:
                batch = ExtractionBatch(workspace_name=workspace_name)
                self._batches[workspace_name] = batch

            batch.message_ids.extend(message_ids)
            if session_name:
                batch.session_names.add(session_name)
            batch.updated_at = time.time()

            # Check if we should flush immediately
            if len(batch.message_ids) >= self.batch_size:
                await self._flush_locked(workspace_name)

    async def _flush_locked(self, workspace_name: str):
        """Flush a specific workspace's batch (must hold lock)."""
        batch = self._batches.pop(workspace_name, None)
        if not batch or not batch.message_ids:
            return

        # Fire and forget - don't await to avoid blocking enqueue
        asyncio.create_task(self._process_batch(batch))

    async def flush_all(self):
        """Flush all pending batches (used on shutdown)."""
        async with self._lock:
            for workspace_name in list(self._batches.keys()):
                await self._flush_locked(workspace_name)

    async def _flush_loop(self):
        """Background task that periodically flushes batches."""
        try:
            while not self._shutdown:
                await asyncio.sleep(self.flush_interval)
                if self._shutdown:
                    break

                async with self._lock:
                    # Find batches that have exceeded flush interval
                    now = time.time()
                    for workspace_name, batch in list(self._batches.items()):
                        if now - batch.updated_at >= self.flush_interval:
                            await self._flush_locked(workspace_name)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Error in extraction flush loop: %s", e)

    async def _process_batch(self, batch: ExtractionBatch):
        """Process a batch of messages for KG extraction."""
        try:
            from src.kg.auto_extractor import get_auto_extractor

            extractor = get_auto_extractor()
            await extractor.extract_from_messages(
                workspace_name=batch.workspace_name,
                message_ids=batch.message_ids,
                session_names=list(batch.session_names),
            )
        except Exception as e:
            logger.exception(
                "Failed to extract KG from batch for workspace %s: %s",
                batch.workspace_name,
                e,
            )


# Global queue instance
_extraction_queue: "ExtractionQueue | None" = None


def get_extraction_queue() -> ExtractionQueue:
    """Get the global extraction queue instance."""
    global _extraction_queue
    if _extraction_queue is None:
        _extraction_queue = ExtractionQueue()
    return _extraction_queue


async def init_extraction_queue() -> ExtractionQueue:
    """Initialize and start the extraction queue."""
    queue = get_extraction_queue()
    await queue.start()
    return queue


async def shutdown_extraction_queue():
    """Shutdown the extraction queue."""
    global _extraction_queue
    if _extraction_queue:
        await _extraction_queue.stop()
        _extraction_queue = None