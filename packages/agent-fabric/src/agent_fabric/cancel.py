"""Cooperative cancellation of a run.

A `CancelToken` is created by the caller, passed to ``AgentFabric.run(..., cancel=token)`` and set from any thread
(a web worker, a signal handler, a timeout). The run checks it before every agent run, LLM call, streamed delta and
pipeline step and stops with a typed `Cancelled` error; work already in flight (a blocking HTTP call) finishes first.
"""

from __future__ import annotations

import threading

from .errors import Cancelled, ErrorDetail


class CancelToken:
    """Thread-safe flag a caller sets to ask a run to stop at its next checkpoint."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason = ""

    def cancel(self, reason: str = "cancelled by caller") -> None:
        """Request cancellation; the first reason wins and later calls are no-ops."""
        if not self._event.is_set():
            self._reason = reason
            self._event.set()

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._event.is_set()

    @property
    def reason(self) -> str:
        """Why the run was cancelled (empty until `cancel` is called)."""
        return self._reason

    def raise_if_cancelled(self, path: str = "") -> None:
        """Raise `Cancelled` located at the agent ``path`` when cancellation was requested."""
        if self._event.is_set():
            where = f" at '{path}'" if path else ""
            raise Cancelled(
                f"run cancelled{where}: {self._reason}",
                [
                    ErrorDetail(
                        loc=("cancel",),
                        type="cancelled",
                        msg=self._reason,
                        hint="the caller asked the run to stop; start a new run to retry",
                    )
                ],
            )


__all__ = ["CancelToken"]
