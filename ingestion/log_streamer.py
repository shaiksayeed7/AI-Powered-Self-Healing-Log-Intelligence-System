"""
Log Streamer – watches log files and emits parsed :class:`LogEntry` objects.

Uses *watchdog* for filesystem events so new lines written to a file are
forwarded immediately.  A callback-based design keeps it decoupled from the
rest of the system.
"""

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path
from threading import Thread
from typing import Optional

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ingestion.log_parser import LogEntry, parse_line


# ---------------------------------------------------------------------------
# Async-friendly log file tail
# ---------------------------------------------------------------------------

class _LogFileHandler(FileSystemEventHandler):
    """Watchdog handler that tails a single log file."""

    def __init__(
        self,
        path: str,
        callback: Callable[[LogEntry], None],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._path = path
        self._callback = callback
        self._loop = loop
        self._fh = open(path, "r", encoding="utf-8", errors="replace")
        # Seek to end so we only process *new* lines
        self._fh.seek(0, os.SEEK_END)

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.src_path != self._path:
            return
        for line in self._fh:
            if line.strip():
                entry = parse_line(line, default_service=Path(self._path).stem)
                # Schedule callback on the event loop from this watchdog thread
                asyncio.run_coroutine_threadsafe(
                    self._dispatch(entry), self._loop
                )

    async def _dispatch(self, entry: LogEntry) -> None:
        self._callback(entry)

    def close(self) -> None:
        self._fh.close()


# ---------------------------------------------------------------------------
# LogStreamer
# ---------------------------------------------------------------------------

class LogStreamer:
    """
    Monitor one or more log file paths for new lines.

    Usage::

        streamer = LogStreamer(["./app.log", "./error.log"])
        streamer.add_listener(my_callback)
        streamer.start()
        ...
        streamer.stop()

    *my_callback* must accept a single :class:`~ingestion.log_parser.LogEntry`
    argument and should be non-blocking (or schedule async work itself).
    """

    def __init__(self, paths: list[str]) -> None:
        self._paths = [str(p) for p in paths]
        self._listeners: list[Callable[[LogEntry], None]] = []
        self._observer: Optional[Observer] = None
        self._handlers: list[_LogFileHandler] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def add_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Register a callback that will be called for every new log entry."""
        self._listeners.append(callback)

    def _dispatch(self, entry: LogEntry) -> None:
        for listener in self._listeners:
            try:
                listener(entry)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start the watchdog observer in a background thread."""
        self._loop = loop or asyncio.get_event_loop()
        self._observer = Observer()

        for path in self._paths:
            if not os.path.isfile(path):
                # Create the file so watchdog can monitor it
                Path(path).touch()

            handler = _LogFileHandler(path, self._dispatch, self._loop)
            self._handlers.append(handler)
            directory = str(Path(path).parent.resolve())
            self._observer.schedule(handler, directory, recursive=False)

        self._observer.start()

    def stop(self) -> None:
        """Stop the watchdog observer and release file handles."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        for h in self._handlers:
            h.close()

    # ------------------------------------------------------------------
    # Simple batch replay (useful for testing / backfill)
    # ------------------------------------------------------------------

    def replay_file(self, path: str) -> list[LogEntry]:
        """
        Parse an existing log file from the beginning and return all entries.
        Does **not** require the streamer to be started.
        """
        entries: list[LogEntry] = []
        service = Path(path).stem
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    entries.append(parse_line(line, default_service=service))
        return entries
