"""Cooperative cancellation token for long-running operations.

A :class:`CancellationToken` can be passed into CPU-intensive functions (e.g. PDF
extraction) that run inside ``asyncio.to_thread``. Those functions periodically
call :meth:`CancellationToken.check` between pages/chunks/figures; when the
WebSocket "stop" handler calls :meth:`CancellationToken.cancel`, the next check
immediately raises :class:`CancellationError`, unwinding the thread and allowing
the async task to clean up.
"""

from __future__ import annotations

import threading


class CancellationError(Exception):
    """Raised when an operation is cancelled by user request."""


class CancellationToken:
    """Thread-safe token that signals a cancellation request.

    Use in the async world (event loop) to call :meth:`cancel` and in the
    synchronous world (worker thread) to call :meth:`check`.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Signal cancellation.  Idempotent — safe to call multiple times."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise :class:`CancellationError` if :meth:`cancel` has been called."""
        if self.is_cancelled:
            raise CancellationError("Operation cancelled by user")
