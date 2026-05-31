"""Logging configuration for transcript downloader."""

import logging
import sys
from typing import Optional

# Default format for log messages
DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
SIMPLE_FORMAT = "%(levelname)s: %(message)s"
VERBOSE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"


class _TTYAwareStreamHandler(logging.StreamHandler):
    """StreamHandler that clears any in-progress countdown/spinner before logging.

    On a TTY, emits ``\\r\\033[K`` (carriage-return + erase-to-end-of-line)
    so that log messages never append to an active countdown or spinner frame.
    No-op on non-interactive streams (pipes, files).
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.stream.isatty():
                self.stream.write("\r\033[K")
                self.stream.flush()
        except Exception:
            pass
        super().emit(record)


def setup_logging(
    level: int = logging.INFO,
    format_string: Optional[str] = None,
    log_file: Optional[str] = None,
    verbose: bool = False,
) -> logging.Logger:
    """
    Configure logging for the transcript downloader.

    Args:
        level: Logging level (default: INFO)
        format_string: Custom format string (optional)
        log_file: Path to log file (optional, logs to file if provided)
        verbose: Use verbose format with file/line info

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("ytscriber")
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Determine format
    if format_string:
        fmt = format_string
    elif verbose:
        fmt = VERBOSE_FORMAT
    else:
        fmt = SIMPLE_FORMAT

    formatter = logging.Formatter(fmt)

    # Console handler
    console_handler = _TTYAwareStreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        logger.addHandler(file_handler)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (optional, uses package name if not provided)

    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f"ytscriber.{name}")
    return logging.getLogger("ytscriber")


# Convenience functions for quick setup
def enable_debug() -> None:
    """Enable debug logging."""
    setup_logging(level=logging.DEBUG, verbose=True)


def enable_quiet() -> None:
    """Enable quiet mode (warnings and errors only)."""
    setup_logging(level=logging.WARNING)
