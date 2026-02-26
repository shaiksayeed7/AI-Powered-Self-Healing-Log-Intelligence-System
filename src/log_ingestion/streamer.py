"""Async log streamer: reads existing content then tails for new lines."""
import asyncio
import os
from typing import AsyncGenerator, List


class LogStreamer:
    """Async generator that streams log lines from a file."""

    def __init__(self, file_path: str):
        self._file_path = file_path
        self._lines: List[str] = []
        self._lock = asyncio.Lock()

    async def stream_lines(self) -> AsyncGenerator[str, None]:
        """Yield existing lines, then tail for new ones."""
        try:
            with open(self._file_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if line.strip():
                        self._lines.append(line)
                        yield line
                pos = fh.tell()

            while True:
                await asyncio.sleep(0.5)
                try:
                    with open(self._file_path, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        new_lines = fh.readlines()
                        pos = fh.tell()
                    for line in new_lines:
                        line = line.rstrip("\n")
                        if line.strip():
                            self._lines.append(line)
                            yield line
                except OSError:
                    await asyncio.sleep(1)
        except OSError:
            return

    def get_recent_lines(self, n: int = 100) -> List[str]:
        return self._lines[-n:]
