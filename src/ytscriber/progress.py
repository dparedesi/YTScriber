"""Terminal progress helpers (countdowns, spinners)."""

from __future__ import annotations

import itertools
import sys
import threading
import time
from typing import Any, Optional


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


def countdown_with_barrier(
    seconds: float,
    message: str = "Next download in",
    future: Any = None,
    future_timeout: float = 300.0,
) -> None:
    """Countdown that also waits for an optional background future to finish.

    Blocks until **both** the rate-limit countdown expires **and** the given
    ``future`` completes (or ``future_timeout`` seconds after the countdown
    ends).  This prevents summary queue build-up when the LLM is slower than
    the inter-download delay.

    On a TTY the status line shows which constraint is still active::

        ⏳ Summarizing + rate-limit wait, 58s...           ← both running
        ⏳ Rate-limit done, summary still running (5s)...  ← waiting on LLM

    When no *future* is given, behaves identically to :func:`countdown_sleep`.
    Never raises — future errors are logged, not propagated.
    """
    if seconds <= 0 and future is None:
        return

    if not _is_interactive():
        time.sleep(max(0, seconds))
        if future is not None:
            try:
                future.result(timeout=future_timeout)
            except Exception:
                pass
        return

    deadline = time.monotonic() + seconds
    hard_stop = deadline + future_timeout
    try:
        while True:
            now = time.monotonic()
            remaining = deadline - now
            summary_done = future.done() if future is not None else True

            if remaining <= 0 and summary_done:
                break
            if now >= hard_stop:
                break

            if remaining > 0:
                sys.stderr.write(
                    f"\r\033[K{message} {int(remaining) + 1}s... "
                )
            else:
                over = int(now - deadline)
                sys.stderr.write(
                    f"\r\033[K⏳ Rate-limit done, summary still running ({over}s)... "
                )
            sys.stderr.flush()
            time.sleep(0.5)
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
