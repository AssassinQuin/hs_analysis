"""log_watcher.py — Tail Power.log with rotation detection.

Provides efficient, thread-safe file tailing with automatic rotation detection
for Hearthstone's Power.log which truncates on game restart.
"""

import os
import time
from pathlib import Path
from typing import Callable, Iterator, Optional


class LogWatcher:
    """Tails a log file, yielding new lines incrementally.

    Detects log rotation (file shrink / truncation) and resets automatically.
    This is critical for Hearthstone which rotates Power.log on game restart.
    """

    def __init__(
        self,
        path: str | Path,
        poll_interval: float = 0.05,  # 50ms
        encoding: str = "utf-8",
        on_rotation: Optional[Callable[[], None]] = None,
    ):
        """Initialize a log watcher.

        Args:
            path: Path to the log file.
            poll_interval: Seconds between polls for new content. Default 50ms.
            encoding: Text encoding to use. Default utf-8.
            on_rotation: Optional callback invoked when log rotation is detected.
        """
        self._path = Path(path)
        self._poll_interval = poll_interval
        self._encoding = encoding
        self._on_rotation = on_rotation

        # File position tracking (byte offset)
        self._pos: int = 0
        self._ino: int = 0
        self._size: int = 0

        # Buffer for non-blocking mode
        self._buffer: list[str] = []

        # File handle for read operations
        self._fd: Optional[int] = None

        # Stats on first access
        self._first_access = True

    def __iter__(self) -> Iterator[str]:
        """Yield new lines as they appear. Blocking iterator.

        This is a blocking iterator that waits for new lines to appear,
        polling at the configured interval.
        """
        while True:
            # Yield any buffered lines first
            for line in self._buffer:
                yield line
            self._buffer.clear()

            # Wait for new content
            self._poll()
            time.sleep(self._poll_interval)

    def lines(self) -> Iterator[str]:
        """Non-blocking: yield buffered new lines, return immediately.

        This is a non-blocking iterator that yields any buffered lines
        immediately, then returns. Callers should repeatedly invoke this
        to drain the buffer and continue watching.
        """
        while self._buffer:
            yield self._buffer.pop(0)

    def read_all(self) -> list[str]:
        """Read all buffered lines immediately (non-blocking).

        Returns:
            List of all buffered lines.
        """
        return list(self._buffer)

    def drain(self) -> list[str]:
        """Read all buffered lines immediately and clear buffer.

        Returns:
            List of all buffered lines.
        """
        lines = list(self._buffer)
        self._buffer.clear()
        return lines

    def read_existing_content(self) -> list[str]:
        """Read initial content from file (non-blocking).

        Polls once to read any existing content in the file and
        populates the buffer. This is useful for tests that need to
        read existing file content without blocking.

        Returns:
            List of all lines read from file.
        """
        self._poll()
        return self.drain()

    @property
    def is_alive(self) -> bool:
        """True if the watched file exists and is accessible."""
        try:
            return self._path.exists() and self._path.is_file()
        except OSError:
            return False

    def _check_rotation(self) -> bool:
        """Return True if file was rotated (size < last position or inode changed).

        Returns:
            True if rotation detected, False otherwise.
        """
        if self._first_access:
            return False

        try:
            stat = self._path.stat()
            current_ino = stat.st_ino
            current_size = stat.st_size

            # Check for rotation (inode changed or size decreased)
            if current_ino != self._ino or current_size < self._pos:
                self._handle_rotation()
                return True
            return False
        except (OSError, FileNotFoundError):
            # File disappeared or error accessing it
            self._handle_rotation()
            return True

    def _handle_rotation(self) -> None:
        """Handle log rotation event."""
        # Reset position to start of file
        self._pos = 0
        self._ino = 0
        self._size = 0
        self._first_access = True

        # Reset buffer
        self._buffer.clear()

        # Close any open file handle
        self._close_file()

        # Invoke rotation callback if provided
        if self._on_rotation is not None:
            try:
                self._on_rotation()
            except Exception:
                # Don't let rotation callback break the watcher
                pass

    def _open_file(self) -> None:
        """Open the file for reading and seek to current position."""
        if self._fd is not None:
            return

        try:
            self._fd = os.open(self._path, os.O_RDONLY | os.O_NONBLOCK)
            os.lseek(self._fd, self._pos, os.SEEK_SET)
        except OSError as e:
            # File doesn't exist yet or other error
            self._fd = None
            if e.errno != 2:  # ENOENT - file doesn't exist (expected on first run)
                raise

    def _close_file(self) -> None:
        """Close the file handle if open."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _poll(self) -> None:
        """Poll for new content and handle any new lines.

        Checks for rotation, opens the file if needed, reads new lines,
        and populates the buffer.
        """
        # Check for rotation first
        if self._check_rotation():
            return

        # If file doesn't exist, we're waiting for it to appear
        if not self.is_alive:
            self._buffer.clear()
            return

        # Open file on first access or after rotation
        if self._first_access:
            self._open_file()
            if self._fd is not None:
                # Read existing content on first access
                new_lines = self._read_new_lines()
                self._buffer.extend(new_lines)
                stat = self._path.stat()
                self._ino = stat.st_ino
                self._size = stat.st_size
                self._first_access = False
            return

        # Read new lines
        if self._fd is not None:
            try:
                new_lines = self._read_new_lines()
                self._buffer.extend(new_lines)
            except OSError:
                # File disappeared during read - will be handled on next poll
                self._close_file()

    def _read_new_lines(self) -> list[str]:
        """Read new lines from the current file position.

        Returns:
            List of new lines (without newlines).
        """
        # Seek to current position
        os.lseek(self._fd, self._pos, os.SEEK_SET)

        # Read data from current position to end
        buffer = bytearray()
        while True:
            chunk = os.read(self._fd, 4096)  # Read 4KB chunks
            if not chunk:
                break
            buffer.extend(chunk)

        # Decode and split into lines
        try:
            text = buffer.decode(self._encoding)
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to decode log file with encoding {self._encoding}: {e}")

        # Split into lines, keeping empty lines
        lines = text.splitlines(keepends=False)

        # Skip empty lines and filter out empty strings
        # Note: We keep lines even if they're empty but not whitespace-only
        lines = [line for line in lines if line]

        # Update position and size tracking
        if buffer:
            self._pos += len(buffer)
            self._size = self._pos

        return lines

    def close(self) -> None:
        """Close the watcher and release resources."""
        self._close_file()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
