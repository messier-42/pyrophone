"""Runtime port traces observe accepted transfers without altering delivery."""

import asyncio

import pytest

import pyrophone as pp
from pyrophone._channels import Channel


@pytest.mark.asyncio
async def test_runtime_ports_trace_values_in_order_and_unregister() -> None:
    values = [{"count": 1}, {"count": 2}]
    received: list[object] = []
    events: list[tuple[str, object]] = []
    subscriptions: list[pp.Trace] = []
    controllers: list[pp.Runtime] = []

    @pp.node_type
    class Source(pp.Node):
        out_port = pp.Output[object]()

        async def run(self) -> None:
            for value in values:
                await self.out_port.send(value)

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[object]()

        async def run(self) -> None:
            async for value in self.in_port:
                received.append(value)

    def configure(runtime: pp.Runtime) -> None:
        controllers.append(runtime)
        source, sink = runtime.nodes
        out_port = source.port("out_port")
        assert source.out_port is out_port
        assert out_port.name == "out_port" and out_port.direction == "output"
        assert out_port.node is source
        assert out_port.schema.type is object
        assert "out_port" in dir(source)
        with pytest.raises(AttributeError):
            source.port("missing")

        def once(value: object) -> None:
            events.append(("once", value))
            subscriptions[0].close()
            subscriptions[0].close()

        subscriptions.append(out_port.trace(once))
        subscriptions.append(
            out_port.trace(lambda value: events.append(("out", value)))
        )
        subscriptions.append(
            sink.port("in_port").trace(lambda value: events.append(("in", value)))
        )
        assert all(trace.active for trace in subscriptions)

    await pp.run_async(
        pp.NodeDeclaration(Source) | pp.NodeDeclaration(Sink), on_runtime=configure
    )
    assert events == [
        ("once", values[0]),
        ("out", values[0]),
        ("in", values[0]),
        ("out", values[1]),
        ("in", values[1]),
    ]
    assert all(a is b for a, b in zip(received, values, strict=True))
    assert events[0][1] is values[0]
    assert not any(trace.active for trace in subscriptions)
    with pytest.raises(RuntimeError, match="stopped"):
        controllers[0].nodes[0].port("out_port").trace(print)
    subscriptions[0].close()


@pytest.mark.asyncio
@pytest.mark.parametrize("receiver_first", [False, True])
async def test_trace_occurs_at_acceptance_even_if_waiter_cancelled_afterward(
    receiver_first: bool,
) -> None:
    channel = Channel[int]()
    events: list[tuple[str, int]] = []
    channel.output._traces.add(lambda value: events.append(("out", value)))
    channel.input._traces.add(lambda value: events.append(("in", value)))
    if receiver_first:
        receiver = asyncio.create_task(channel.input.recv())
        await asyncio.sleep(0)
        assert events == []
        await channel.output.send(3)
        receiver.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receiver
    else:
        sender = asyncio.create_task(channel.output.send(3))
        await asyncio.sleep(0)
        assert events == []
        assert await channel.input.recv() == 3
        sender.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sender
    assert events == [("out", 3), ("in", 3)]


@pytest.mark.asyncio
async def test_unaccepted_sends_do_not_trace() -> None:
    channel = Channel[int]()
    values: list[int] = []
    channel.output._traces.add(values.append)
    sender = asyncio.create_task(channel.output.send(1))
    await asyncio.sleep(0)
    sender.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sender
    other = asyncio.create_task(channel.output.send(2))
    await asyncio.sleep(0)
    await channel.input.close()
    with pytest.raises(pp.ChannelClosedError):
        await other
    assert values == []


@pytest.mark.asyncio
async def test_registration_changes_apply_to_next_handoff() -> None:
    channel = Channel[int]()
    events: list[tuple[str, int]] = []
    target = channel.input._traces.add(lambda value: events.append(("input", value)))

    def change(value: int) -> None:
        target.close()
        source.close()
        channel.input._traces.add(lambda value: events.append(("new", value)))

    source = channel.output._traces.add(change)
    for value in (1, 2):
        sender = asyncio.create_task(channel.output.send(value))
        assert await channel.input.recv() == value
        await sender
    assert events == [("input", 1), ("new", 2)]


@pytest.mark.asyncio
async def test_callback_errors_and_disguised_coroutines_do_not_break_delivery(
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = Channel[int]()
    seen: list[int] = []

    def broken(value: int) -> None:
        raise ValueError("trace failed")

    async def asynchronous(value: int) -> None:
        pytest.fail("must not run coroutine")

    class AsyncCallable:
        async def __call__(self, value: int) -> None:
            pass

    for callback in (asynchronous, AsyncCallable()):
        with pytest.raises(TypeError, match="synchronous"):
            channel.input._traces.add(callback)  # type: ignore[arg-type]
    channel.input._traces.add(broken)
    channel.input._traces.add(lambda value: asynchronous(value))  # type: ignore[arg-type]
    channel.input._traces.add(seen.append)
    sender = asyncio.create_task(channel.output.send(5))
    assert await channel.input.recv() == 5
    await sender
    assert seen == [5]
    assert "trace failed" in caplog.text
    assert "awaitable" in caplog.text


@pytest.mark.asyncio
async def test_trace_registration_rejects_other_threads() -> None:
    controllers: list[pp.Runtime] = []
    ready = asyncio.Event()

    @pp.node_type
    class Loop(pp.Node):
        incoming = pp.Input[int]()
        outgoing = pp.Output[int]()

        async def run(self) -> None:
            ready.set()
            await asyncio.Event().wait()

    declaration = pp.NodeDeclaration(Loop)
    graph = pp.Graph(declaration).connect(declaration.outgoing, declaration.incoming)
    async with asyncio.TaskGroup() as tasks:
        task = tasks.create_task(pp.run_async(graph, on_runtime=controllers.append))
        await ready.wait()
        port = controllers[0].nodes[0].port("outgoing")
        trace = port.trace(print)

        def from_thread() -> None:
            with pytest.raises(RuntimeError, match="event loop"):
                port.trace(print)
            with pytest.raises(RuntimeError, match="event loop"):
                trace.close()

        await asyncio.to_thread(from_thread)
        task.cancel()
    assert not trace.active
