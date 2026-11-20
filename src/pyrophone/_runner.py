"""Synchronous execution without command-line policy."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Coroutine

from ._compile import CompiledGraph
from ._graph import Graph
from ._runtime import run_async

type _Factory = Callable[[], Graph | Awaitable[Graph]]


def _run_entry(entry: Callable[[], Coroutine[object, object, None]]) -> None:
    # Check before constructing a coroutine, so misuse cannot leak an unawaited one.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "A synchronous Pyrophone entry point cannot run inside an active "
            "event loop; use await pyrophone.run_async(graph) instead."
        )
    try:
        asyncio.run(entry())
    except KeyboardInterrupt:
        # asyncio.run has already cancelled tasks and awaited their cleanup.
        pass


def run_sync(
    graph: Graph | _Factory,
    *,
    on_graph: Callable[[CompiledGraph], None] | None = None,
    execute: bool = True,
) -> None:
    """Run a graph or zero-argument graph factory in a new event loop.

    Graph factories may be synchronous or asynchronous. Construction and graph
    execution share the same loop. No command-line arguments are parsed.
    on_graph observes the validated snapshot before live node creation;
    execute=False stops after validation and observation.

    Ctrl-C cancels execution and completes cooperative cleanup without a
    traceback. Other failures propagate. Inside an existing event loop, use
    ``await run_async(graph)`` instead.
    """
    _run_entry(lambda: _run_target(graph, on_graph=on_graph, execute=execute))


async def _run_target(
    target: Graph | _Factory,
    *,
    on_graph: Callable[[CompiledGraph], None] | None,
    execute: bool,
) -> None:
    graph = target if isinstance(target, Graph) else target()
    if inspect.isawaitable(graph):
        graph = await graph
    if not isinstance(graph, Graph):
        raise TypeError("A Pyrophone graph factory must return a Graph")
    await run_async(graph, on_graph=on_graph, execute=execute)
