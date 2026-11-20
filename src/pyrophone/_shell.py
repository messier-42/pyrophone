"""Async stdio inspection of a running graph."""

import asyncio
import signal
import sys
from contextlib import closing
from typing import TextIO

from aioconsole import AsynchronousConsole  # type: ignore[import-untyped]
from prompt_toolkit import PromptSession
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_input
from prompt_toolkit.output import create_output

from ._compile import CompiledGraph
from ._graph import Graph
from ._terminal import coordinated_output


class _ConsoleWriter:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    def write(self, data: bytes) -> None:
        self.stream.write(data.decode())

    async def drain(self) -> None:
        self.stream.flush()


class _Console(AsynchronousConsole):  # type: ignore[misc]
    def __init__(
        self,
        namespace: dict[str, object],
        prompt: PromptSession[str] | None = None,
        output: TextIO | None = None,
    ) -> None:
        self._prompt = prompt
        # In terminal mode prompt-toolkit exclusively owns stdin. Do not let
        # aioconsole also attach a read transport to the same descriptor.
        streams = (None, _ConsoleWriter(output)) if output is not None else None
        super().__init__(locals=namespace, streams=streams)
        if prompt is not None:
            self.locals["ainput"] = self.raw_input

    async def raw_input(self, prompt: str = "") -> str:
        if self._prompt is None:
            result: str = await super().raw_input(prompt)
            return result
        try:
            return await self._prompt.prompt_async(prompt, handle_sigint=False)
        except KeyboardInterrupt:
            # Let aioconsole reset multiline input using its usual Ctrl-C path.
            self._sigint_received = True
            raise asyncio.CancelledError from None

    def showtraceback(self) -> None:
        # aioconsole catches BaseException during evaluation. Let cancellation
        # reach its input loop so graph shutdown cannot get stuck at a new prompt.
        error = sys.exception()
        if isinstance(error, asyncio.CancelledError):
            raise error
        super().showtraceback()


async def run_shell(
    graph: Graph, compiled_graph: CompiledGraph, graph_task: asyncio.Task[None]
) -> None:
    """Read stdin and write prompts/results to stderr without blocking the graph.

    Ctrl-C interrupts a command; EOF, exit(), and quit() return to the runtime,
    which cancels the graph and awaits its cleanup.
    """
    from . import script

    namespace = {name: getattr(script, name) for name in script.__all__}
    namespace.update(graph=graph, compiled_graph=compiled_graph, graph_task=graph_task)
    if sys.stdin.isatty() and sys.stderr.isatty():
        with closing(create_input(stdin=sys.stdin)) as terminal_input:
            with create_app_session(
                input=terminal_input, output=create_output(stdout=sys.stderr)
            ):
                prompt = PromptSession[str]()
                output = sys.stderr
                with coordinated_output():
                    await _interact(_Console(namespace, prompt, output))
    else:
        await _interact(_Console(namespace))


async def _interact(console: _Console) -> None:
    previous_sigint = signal.getsignal(signal.SIGINT)
    try:
        await console.interact(
            banner=(
                "Pyrophone shell (top-level await supported).\n"
                "Available: graph, compiled_graph, graph_task, asyncio, loop, "
                "and pyrophone.script names.\n"
                "Ctrl-C interrupts a command; Ctrl-D or exit() stops the graph."
            ),
            stop=False,
        )
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
