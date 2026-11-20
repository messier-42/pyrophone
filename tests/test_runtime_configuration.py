"""External handles edit live configuration without changing startup snapshots."""

import asyncio
import io
from typing import cast

import pytest

import pyrophone as pp


@pytest.mark.asyncio
async def test_assignment_updates_one_live_instance_and_preserves_snapshots() -> None:
    started, resume = asyncio.Event(), asyncio.Event()
    seen: list[tuple[int, int]] = []
    live: list[pp.Node] = []
    controllers: list[pp.Runtime] = []

    @pp.node_type
    class Worker(pp.Node):
        amount = pp.Property[int](default=2, minimum=0, maximum=20)

        def __init__(self) -> None:
            live.append(self)

        async def run(self) -> None:
            before = self.amount
            started.set()
            await resume.wait()
            seen.append((before, self.amount))

    first, second = pp.NodeDeclaration(Worker), pp.NodeDeclaration(Worker)
    graph = pp.Graph(first, second)

    async def session(
        original: pp.Graph, compiled: pp.CompiledGraph, task: asyncio.Task[None]
    ) -> None:
        await started.wait()
        runtime = controllers[0]
        adder = runtime.nodes[0]
        assert adder.id == first.id
        assert adder.node_type is Worker
        assert adder.schema is first.schema
        assert adder.active
        assert adder.amount == 2
        old = adder.configuration
        adder.amount = 10
        assert adder.amount == 10
        assert live[0]._configuration["amount"] == 10
        assert runtime.nodes[1].amount == 2
        assert old["amount"] == 2
        assert original.nodes[0].configuration["amount"] == 2
        assert compiled.nodes[0].configuration["amount"] == 2
        with pytest.raises(AttributeError, match="read-only"):
            setattr(live[0], "amount", 4)  # noqa: B010
        for value in ("bad", -1, 21):
            with pytest.raises(pp.ConfigurationError):
                adder.amount = value
            assert adder.amount == 10
        with pytest.raises(AttributeError):
            adder.amout = 3
        with pytest.raises(AttributeError):
            setattr(adder, "id", "changed")  # noqa: B010
        stream = io.StringIO()
        adder.print(file=stream)
        assert "amount: 10" in stream.getvalue()
        assert "Worker" in repr(adder) and first.id[:8] in repr(adder)
        resume.set()
        await task

    async with asyncio.timeout(2):
        await pp.run_async(graph, on_runtime=controllers.append, session=session)
    assert sorted(seen) == [(2, 2), (2, 10)]
    adder = controllers[0].nodes[0]
    assert not adder.active
    assert adder.amount == 10
    with pytest.raises(RuntimeError, match="stopped"):
        adder.amount = 5


@pytest.mark.asyncio
async def test_mutable_values_are_detached_on_assignment_and_inspection() -> None:
    controllers: list[pp.Runtime] = []

    @pp.node_type
    class Worker(pp.Node):
        settings = pp.Property[dict[str, list[int]]](default={"items": [1]})
        # Handle metadata names remain reachable through the named API.
        configuration = pp.Property[str](default="original")

        async def run(self) -> None:
            assert self.settings == {"items": [2]}
            assert self.configuration == "changed"

    def inspect(runtime: pp.Runtime) -> None:
        controllers.append(runtime)
        handle = runtime.nodes[0]
        value = {"items": [2]}
        handle.settings = value
        value["items"].append(3)
        read = handle.settings
        read["items"].append(4)
        snapshot = handle.configuration
        cast(dict[str, list[int]], snapshot["settings"])["items"].append(5)
        assert handle.settings == {"items": [2]}
        with pytest.raises(TypeError):
            cast(dict[str, object], snapshot)["settings"] = {}
        with pytest.raises(AttributeError):
            setattr(handle, "configuration", {})  # noqa: B010
        handle.set_property("configuration", "changed")
        assert handle.get_property("configuration") == "changed"
        with pytest.raises(AttributeError):
            handle.set_property("missing", 1)
        with pytest.raises(AttributeError):
            handle.get_property("missing")

    await pp.run_async(pp.Graph(pp.NodeDeclaration(Worker)), on_runtime=inspect)
    assert controllers[0].nodes[0].settings == {"items": [2]}


def test_sync_runner_exposes_runtime_and_dump_skips_it() -> None:
    values: list[int] = []

    @pp.node_type
    class Worker(pp.Node):
        amount = pp.Property[int](default=2)

        async def run(self) -> None:
            values.append(self.amount)

    def configure(runtime: pp.Runtime) -> None:
        runtime.nodes[0].amount = 10

    graph = pp.Graph(pp.NodeDeclaration(Worker))
    pp.run_sync(graph, on_runtime=configure)
    pp.run_sync(graph)
    assert values == [10, 2]
    pp.run_sync(graph, execute=False, on_runtime=lambda runtime: pytest.fail("ran"))


@pytest.mark.asyncio
async def test_stopped_nodes_reject_changes_while_siblings_run() -> None:
    finished, release = asyncio.Event(), asyncio.Event()
    controllers: list[pp.Runtime] = []

    @pp.node_type
    class Quick(pp.Node):
        amount = pp.Property[int](default=1)

        async def run(self) -> None:
            finished.set()

    @pp.node_type
    class Slow(pp.Node):
        async def run(self) -> None:
            await release.wait()

    async def session(
        graph: pp.Graph, compiled: pp.CompiledGraph, task: asyncio.Task[None]
    ) -> None:
        await finished.wait()
        handle = controllers[0].nodes[0]
        assert not handle.active
        with pytest.raises(RuntimeError, match="stopped"):
            handle.amount = 3
        release.set()
        await task

    async with asyncio.timeout(2):
        await pp.run_async(
            pp.Graph(pp.NodeDeclaration(Quick), pp.NodeDeclaration(Slow)),
            on_runtime=controllers.append,
            session=session,
        )


@pytest.mark.asyncio
async def test_callback_failure_closes_handles_and_bindings() -> None:
    controllers: list[pp.Runtime] = []
    endpoints: list[pp.OutputPort[int]] = []

    @pp.node_type
    class Loop(pp.Node):
        amount = pp.Property[int](default=1)
        incoming = pp.Input[int]()
        outgoing = pp.Output[int]()

        def __init__(self) -> None:
            endpoints.append(self.outgoing)

        async def run(self) -> None:
            pytest.fail("must not start after callback failure")

    def fail(runtime: pp.Runtime) -> None:
        controllers.append(runtime)
        raise ValueError("callback failed")

    declaration = pp.NodeDeclaration(Loop)
    graph = pp.Graph(declaration).connect(declaration.outgoing, declaration.incoming)
    with pytest.raises(ValueError, match="callback failed"):
        await pp.run_async(graph, on_runtime=fail)
    assert not controllers[0].nodes[0].active
    with pytest.raises(pp.ChannelClosedError):
        await endpoints[0].send(1)


@pytest.mark.asyncio
async def test_updates_require_owning_loop_and_handles_close_on_cancellation() -> None:
    ready = asyncio.Event()
    controllers: list[pp.Runtime] = []

    @pp.node_type
    class Worker(pp.Node):
        amount = pp.Property[int](default=1)

        async def run(self) -> None:
            ready.set()
            await asyncio.Event().wait()

    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        task = tasks.create_task(
            pp.run_async(
                pp.Graph(pp.NodeDeclaration(Worker)), on_runtime=controllers.append
            )
        )
        await ready.wait()
        handle = controllers[0].nodes[0]

        def from_thread() -> None:
            with pytest.raises(RuntimeError, match="event loop"):
                handle.amount = 9

        await asyncio.to_thread(from_thread)
        assert handle.amount == 1
        task.cancel()
    assert not handle.active
    with pytest.raises(RuntimeError, match="stopped"):
        handle.amount = 2


@pytest.mark.asyncio
async def test_copy_failure_does_not_modify_configuration() -> None:
    class CannotCopy:
        def __deepcopy__(self, memo: dict[int, object]) -> object:
            raise ValueError("cannot copy")

    @pp.node_type
    class Worker(pp.Node):
        value = pp.Property[object](default=1)

        async def run(self) -> None:
            assert self.value == 1

    def configure(runtime: pp.Runtime) -> None:
        handle = runtime.nodes[0]
        with pytest.raises(ValueError, match="cannot copy"):
            handle.value = CannotCopy()
        assert handle.value == 1

    await pp.run_async(pp.Graph(pp.NodeDeclaration(Worker)), on_runtime=configure)
