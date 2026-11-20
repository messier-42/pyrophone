"""Graph execution owns fresh bindings, structured tasks, and endpoint cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

import pytest

import pyrophone as pp


def declare(cls: type[pp.Node], **configuration: object) -> pp.NodeDeclaration:
    return cast(Callable[..., pp.NodeDeclaration], cls)(**configuration)


def current_task() -> asyncio.Task[object]:
    task = asyncio.current_task()
    assert task is not None
    return task


def node_errors(
    group: BaseExceptionGroup[BaseException],
) -> list[pp.NodeExecutionError]:
    errors: list[pp.NodeExecutionError] = []
    for error in group.exceptions:
        if isinstance(error, BaseExceptionGroup):
            errors.extend(node_errors(error))
        else:
            assert isinstance(error, pp.NodeExecutionError)
            errors.append(error)
    return errors


@pytest.mark.asyncio
async def test_pipeline_drains_and_every_execution_has_fresh_initialized_bindings() -> (
    None
):
    sources: list[pp.Node] = []
    sinks: list[pp.Node] = []
    outputs: list[pp.OutputPort[int]] = []
    inputs: list[pp.InputPort[int]] = []
    results: list[list[int]] = []
    running: list[asyncio.Task[object]] = []

    @pp.node_type
    class Source(pp.Node):
        count = pp.Property[int](default=3)
        out_port = pp.Output[int]()

        def __init__(self) -> None:
            assert self.count == 4
            sources.append(self)
            outputs.append(self.out_port)
            self.position = 0

        async def run(self) -> None:
            running.append(current_task())
            while self.position < self.count:
                await self.out_port.send(self.position)
                self.position += 1

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[int]()

        def __init__(self) -> None:
            sinks.append(self)
            inputs.append(self.in_port)
            self.values: list[int] = []
            results.append(self.values)

        async def run(self) -> None:
            running.append(current_task())
            async for value in self.in_port:
                self.values.append(value)

    graph = declare(Source, count=4) | declare(Sink)
    assert not sources and not sinks
    async with asyncio.timeout(2):
        await pp.run(graph)
        await pp.run(graph)
    assert results == [[0, 1, 2, 3], [0, 1, 2, 3]]
    assert len(sources) == len(sinks) == 2
    assert sources[0] is not sources[1] and sinks[0] is not sinks[1]
    assert outputs[0] is not outputs[1] and inputs[0] is not inputs[1]
    assert len(running) == 4 and all(task.done() for task in running)
    for output in outputs:
        with pytest.raises(pp.ChannelClosedError):
            await output.send(9)
    for input_port in inputs:
        with pytest.raises(pp.EndOfStream):
            await input_port.recv()


@pytest.mark.asyncio
async def test_empty_and_portless_graphs() -> None:
    calls: list[str] = []

    @pp.node_type
    class Plain(pp.Node):
        def __init__(self) -> None:
            calls.append("init")

        async def run(self) -> None:
            calls.append("run")

    await pp.run(pp.Graph())
    await pp.run(pp.Graph(declare(Plain)))
    assert calls == ["init", "run"]


@pytest.mark.asyncio
async def test_invalid_graph_does_not_initialize_any_node() -> None:
    calls: list[str] = []

    @pp.node_type
    class Plain(pp.Node):
        def __init__(self) -> None:
            calls.append("init")

    @pp.node_type
    class Disconnected(pp.Node):
        in_port = pp.Input[int]()

    with pytest.raises(pp.GraphError, match="unconnected"):
        await pp.run(pp.Graph(declare(Plain), declare(Disconnected)))
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_side", ["source", "sink"])
async def test_run_failure_has_context_and_terminates_sibling(
    failure_side: str,
) -> None:
    source_started, sink_started = asyncio.Event(), asyncio.Event()
    finalized: set[str] = set()
    running: list[asyncio.Task[object]] = []
    original = ValueError("node exploded")

    @pp.node_type
    class Source(pp.Node):
        out_port = pp.Output[int]()

        async def run(self) -> None:
            running.append(current_task())
            try:
                source_started.set()
                if failure_side == "source":
                    await sink_started.wait()
                    raise original
                await self.out_port.send(1)
            finally:
                finalized.add("source")

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[int]()

        async def run(self) -> None:
            running.append(current_task())
            try:
                sink_started.set()
                if failure_side == "sink":
                    await source_started.wait()
                    raise original
                await asyncio.Event().wait()
            finally:
                finalized.add("sink")

    source, sink = declare(Source), declare(Sink)
    async with asyncio.timeout(2):
        with pytest.raises(ExceptionGroup) as caught:
            await pp.run(source | sink)
    errors = node_errors(caught.value)
    error = next(error for error in errors if error.__cause__ is original)
    failing = source if failure_side == "source" else sink
    assert error.node_id == failing.id
    assert error.node_type is failing.node_type
    assert error.node_type_name == failing.node_type.__name__
    assert failing.id in str(error) and error.node_type_name in str(error)
    assert finalized == {"source", "sink"}
    assert len(running) == 2 and all(task.done() for task in running)


@pytest.mark.asyncio
async def test_external_cancellation_awaits_cooperative_finally_cleanup() -> None:
    started = asyncio.Event()
    cleaning = asyncio.Event()
    allow_cleanup = asyncio.Event()
    finished = asyncio.Event()
    running: list[asyncio.Task[object]] = []

    @pp.node_type
    class Worker(pp.Node):
        async def run(self) -> None:
            running.append(current_task())
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await allow_cleanup.wait()
                finished.set()

    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        graph_task = tasks.create_task(pp.run(pp.Graph(declare(Worker))))
        await started.wait()
        graph_task.cancel()
        await cleaning.wait()
        assert not graph_task.done() and not finished.is_set()
        allow_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await graph_task
    assert finished.is_set()
    assert len(running) == 1 and running[0].done()


@pytest.mark.asyncio
async def test_early_sink_completion_rejects_upstream_send() -> None:
    running: list[asyncio.Task[object]] = []

    @pp.node_type
    class Source(pp.Node):
        out_port = pp.Output[int]()

        async def run(self) -> None:
            running.append(current_task())
            await self.out_port.send(1)
            await self.out_port.send(2)

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[int]()

        async def run(self) -> None:
            running.append(current_task())
            assert await self.in_port.recv() == 1

    source = declare(Source)
    async with asyncio.timeout(2):
        with pytest.raises(ExceptionGroup) as caught:
            await pp.run(source | declare(Sink))
    errors = node_errors(caught.value)
    assert len(errors) == 1
    assert errors[0].node_id == source.id
    assert isinstance(errors[0].__cause__, pp.ChannelClosedError)
    assert len(running) == 2 and all(task.done() for task in running)


@pytest.mark.asyncio
async def test_initializer_failure_closes_all_bindings_without_starting_nodes() -> None:
    outputs: list[pp.OutputPort[int]] = []
    inputs: list[pp.InputPort[int]] = []
    calls: list[str] = []
    original = RuntimeError("initialization exploded")

    @pp.node_type
    class Source(pp.Node):
        out_port = pp.Output[int]()

        def __init__(self) -> None:
            outputs.append(self.out_port)

        async def run(self) -> None:
            calls.append("run")

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[int]()

        def __init__(self) -> None:
            inputs.append(self.in_port)
            raise original

    sink = declare(Sink)
    async with asyncio.timeout(2):
        with pytest.raises(pp.NodeExecutionError) as caught:
            await pp.run(declare(Source) | sink)
        assert caught.value.__cause__ is original
        assert caught.value.node_id == sink.id
        assert caught.value.node_type is Sink
        assert caught.value.node_type_name == "Sink"
        assert calls == []
        with pytest.raises(pp.ChannelClosedError):
            await outputs[0].send(1)
        with pytest.raises(pp.EndOfStream):
            await inputs[0].recv()
