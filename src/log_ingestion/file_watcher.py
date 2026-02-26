"""Watchdog-based log file watcher."""
import os
import time
import threading
from typing import Callable, List

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class _LogFileEventHandler(FileSystemEventHandler):
    def __init__(self, file_path: str, callback: Callable[[List[str]], None]):
        super().__init__()
        self._file_path = os.path.abspath(file_path)
        self._callback = callback
        self._pos = self._current_size()

    def _current_size(self) -> int:
        try:
            return os.path.getsize(self._file_path)
        except OSError:
            return 0

    def on_modified(self, event):
        if os.path.abspath(event.src_path) != self._file_path:
            return
        try:
            with open(self._file_path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._pos)
                new_lines = fh.readlines()
                self._pos = fh.tell()
            if new_lines:
                self._callback([l.rstrip("\n") for l in new_lines if l.strip()])
        except OSError:
            pass


class LogFileWatcher:
    """Monitors a log file for new appended lines via watchdog."""

    def __init__(self, file_path: str, callback: Callable[[List[str]], None]):
        self._file_path = file_path
        self._callback = callback
        self._observer: Observer = Observer()
        self._handler = _LogFileEventHandler(file_path, callback)

    def start(self) -> None:
        watch_dir = os.path.dirname(os.path.abspath(self._file_path)) or "."
        self._observer.schedule(self._handler, path=watch_dir, recursive=False)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
