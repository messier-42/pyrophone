"""Coordinate terminal writes with the active input editor."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO, cast

from prompt_toolkit.patch_stdout import StdoutProxy


class _SessionOutputProxy(StdoutProxy):
    def __init__(self) -> None:
        self._context = contextvars.copy_context()
        super().__init__()

    def _write_and_flush(
        self, loop: asyncio.AbstractEventLoop | None, text: str
    ) -> None:
        # The flush worker is a thread. Its callbacks must enter the shell's
        # app session, or run_in_terminal cannot find the prompt to redraw.
        self._context.copy().run(super()._write_and_flush, loop, text)


def _stream_handlers() -> set[logging.StreamHandler[TextIO]]:
    loggers = [logging.getLogger()]
    loggers.extend(
        logger
        for logger in logging.Logger.manager.loggerDict.copy().values()
        if isinstance(logger, logging.Logger)
    )
    return {
        handler
        for logger in loggers
        for handler in logger.handlers[:]
        if isinstance(handler, logging.StreamHandler)
    }


@contextmanager
def coordinated_output() -> Iterator[None]:
    """Redraw around terminal writes, including already-configured log handlers.

    An active prompt-toolkit app session selects the terminal output. Preserve
    redirected stdout and file handlers, and restore streams when the shell ends.
    """
    stdout, stderr = sys.stdout, sys.stderr
    terminal_streams = [stderr]
    if stdout.isatty():
        terminal_streams.append(stdout)
    with _SessionOutputProxy() as output:
        proxy = cast(TextIO, output)
        original_streams = {}
        try:
            sys.stderr = proxy
            if stdout.isatty():
                sys.stdout = proxy
            for handler in _stream_handlers():
                if any(handler.stream is stream for stream in terminal_streams):
                    original_streams[handler] = handler.stream
                    handler.setStream(proxy)
            yield
        finally:
            # Include handlers created during the session, whose default stream
            # is the proxy. Do not overwrite an explicitly changed destination.
            for handler in _stream_handlers() | original_streams.keys():
                if handler.stream is proxy:
                    handler.setStream(original_streams.get(handler, stderr))
            sys.stdout, sys.stderr = stdout, stderr
