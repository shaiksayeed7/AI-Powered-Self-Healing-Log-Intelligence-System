"""Real-Time Log Streamer.

Monitors a log file for new lines and feeds them through the parser.
Uses asyncio so it can run alongside the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Callable, Optional

from sentinelai.log_ingestion.parser import parse_log_line
from sentinelai.config import LOG_POLL_INTERVAL_SECONDS


class LogStreamer:
    """Tail a log file asynchronously, yielding parsed log records.

    Parameters
    ----------
    path:
        Path to the log file to monitor.
    on_record:
        Optional async callback invoked for every successfully parsed record.
    poll_interval:
        Seconds between file-read polls (default from config).
    """

    def __init__(
        self,
        path: str,
        on_record: Optional[Callable[[dict], None]] = None,
        poll_interval: float = LOG_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.path = path
        self.on_record = on_record
        self.poll_interval = poll_interval
        self._running = False

    async def stream(self) -> AsyncIterator[dict]:
        """Yield parsed log records as they appear in the file."""
        self._running = True
        # Open at the end so we only see *new* lines
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            while self._running:
                line = fh.readline()
                if line:
                    record = parse_log_line(line)
                    if record is not None:
                        if self.on_record:
                            self.on_record(record)
                        yield record
                else:
                    await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        """Signal the stream loop to stop."""
        self._running = False


async def stream_file_from_start(path: str) -> AsyncIterator[dict]:
    """Parse an *existing* log file from the beginning (useful for batch mode).

    Yields parsed records without waiting for new content.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            record = parse_log_line(line)
            if record is not None:
                yield record
