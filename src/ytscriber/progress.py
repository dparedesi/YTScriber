"""Terminal progress helpers (countdowns, spinners)."""

from __future__ import annotations

import itertools
import sys
import threading
import time
from typing import Optional


def _is_interactive() -> bool:
    """True when stderr is a real terminal we can draw live updates on."""
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


def countdown_sleep(seconds: float, message: str = "Next download in") -> None:
    """Sleep for ``seconds`` while showing a live countdown on a TTY.

    On a non-interactive stream (piped output, log file) this just sleeps so
    log files stay clean. Never raises.
    """
    if seconds <= 0:
        return

    if not _is_interactive():
        time.sleep(seconds)
        return

    end = time.monotonic() + seconds
    try:
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            sys.stderr.write(f"\r\033[K{message} {int(remaining) + 1}s... ")
            sys.stderr.flush()
            time.sleep(min(1.0, remaining))
    finally:
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()


class Spinner:
    """A minimal background spinner for indeterminate waits on a TTY.

    Use as a context manager. No-op on non-interactive streams.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str) -> None:
        self.message = message
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active = _is_interactive()

    def _spin(self) -> None:
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            sys.stderr.write(f"\r\033[K{frame} {self.message} ")
            sys.stderr.flush()
            time.sleep(0.1)

    def __enter__(self) -> "Spinner":
        if self._active:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        if self._active:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()
