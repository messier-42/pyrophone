"""Synchronous observers of accepted channel handoffs."""

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import cast

_logger = logging.getLogger(__name__)


class Trace:
    """A port trace registration. close() removes it synchronously and idempotently."""

    def __init__(
        self, callback: Callable[[object], None], remove: Callable[[], object]
    ) -> None:
        self._callback: Callable[[object], None] | None = callback
        self._remove = remove
        self._loop = asyncio.get_running_loop()

    @property
    def active(self) -> bool:
        return self._callback is not None

    def close(self) -> None:
        """Stop future notifications; call from the runtime's event loop."""
        if not self.active:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not self._loop:
            raise RuntimeError("trace changes must run on the node's event loop")
        self._remove()
        self._deactivate()

    def _deactivate(self) -> None:
        self._callback = None

    def __repr__(self) -> str:
        return f"Trace(active={self.active})"


class _TraceCallbacks[T]:
    def __init__(self) -> None:
        self._traces: dict[object, Trace] = {}
        self._closed = False

    def add(self, callback: Callable[[T], None]) -> Trace:
        if self._closed:
            raise RuntimeError("port has closed")
        call = getattr(callback, "__call__", None)  # noqa: B004 - inspect async callable objects
        if not callable(callback) or any(
            inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)
            for fn in (callback, call)
        ):
            raise TypeError("trace callbacks must be synchronous callables")
        token = object()
        trace = Trace(
            cast(Callable[[object], None], callback),
            lambda: self._traces.pop(token, None),
        )
        self._traces[token] = trace
        return trace

    def snapshot(self) -> tuple[Callable[[object], None], ...]:
        return tuple(
            trace._callback
            for trace in self._traces.values()
            if trace._callback is not None
        )

    def close(self) -> None:
        self._closed = True
        for trace in self._traces.values():
            trace._deactivate()
        self._traces.clear()


def _notify(callbacks: tuple[Callable[[object], None], ...], value: object) -> None:
    for callback in callbacks:
        try:
            result: object = callback(value)
            if inspect.isawaitable(result) or inspect.isasyncgen(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError(
                    "trace callback returned an awaitable or async generator"
                )
        except Exception:
            _logger.exception("Port trace callback failed")
