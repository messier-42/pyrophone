"""Transform is an ordinary node with inherited, concrete port types."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

import pytest

import pyrophone as pp
from pyrophone.nodes import Transform


def declare(cls: type[pp.Node], **configuration: object) -> pp.NodeDeclaration:
    return cast(Callable[..., pp.NodeDeclaration], cls)(**configuration)


@pp.node_type
class Source(pp.Node):
    out_port = pp.Output[int]()

    async def run(self) -> None:
        for value in (1, 2, 3):
            await self.out_port.send(value)


@pp.node_type
class Add(Transform[int, int]):
    amount = pp.Property[int](
        default=1,
        title="Amount",
        description="The amount added to each incoming value.",
        step=1,
    )

    async def transform(self, value: int) -> int:
        return value + self.amount


@pytest.fixture
def sink() -> tuple[pp.NodeDeclaration, list[int]]:
    values: list[int] = []

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[int]()

        async def run(self) -> None:
            async for value in self.in_port:
                values.append(value)

    return declare(Sink), values


@pytest.mark.asyncio
async def test_transform_pipeline(sink: tuple[pp.NodeDeclaration, list[int]]) -> None:
    destination, values = sink
    async with asyncio.timeout(2):
        await pp.run(declare(Source) | declare(Add, amount=3) | destination)
    assert values == [4, 5, 6]


@pytest.mark.asyncio
async def test_transform_matches_handwritten_run(
    sink: tuple[pp.NodeDeclaration, list[int]],
) -> None:
    destination, values = sink

    @pp.node_type
    class Handwritten(pp.Node):
        amount = pp.Property[int](default=1)
        in_port = pp.Input[int]()
        out_port = pp.Output[int]()

        async def run(self) -> None:
            async for value in self.in_port:
                await self.out_port.send(value + self.amount)

    async with asyncio.timeout(2):
        await pp.run(declare(Source) | declare(Add, amount=3) | destination)
        expected = values.copy()
        values.clear()
        await pp.run(declare(Source) | declare(Handwritten, amount=3) | destination)
    assert values == expected == [4, 5, 6]


@pytest.mark.asyncio
async def test_transform_declarations_have_independent_live_state(
    sink: tuple[pp.NodeDeclaration, list[int]],
) -> None:
    instances: list[TrackingAdd] = []

    @pp.node_type
    class TrackingAdd(Add):
        def __init__(self) -> None:
            self.seen: list[int] = []
            instances.append(self)

        async def transform(self, value: int) -> int:
            self.seen.append(value)
            return await super().transform(value)

    destination, values = sink
    first, second = declare(TrackingAdd, amount=3), declare(TrackingAdd, amount=5)
    assert not instances
    async with asyncio.timeout(2):
        await pp.run(declare(Source) | first | second | destination)
    assert values == [9, 10, 11]
    assert len(instances) == 2
    left, right = instances
    assert left is not right
    assert (left.amount, right.amount) == (3, 5)
    assert left.seen == [1, 2, 3]
    assert right.seen == [4, 5, 6]
    assert left.seen is not right.seen
    assert left.in_port is not right.in_port
    assert left.out_port is not right.out_port


def test_concrete_transform_schema_resolves_inherited_ports() -> None:
    schema = pp.node_type_schema(Add)
    assert schema.inputs["in_port"].type is int
    assert schema.outputs["out_port"].type is int
    assert schema.inputs["in_port"].description
    assert schema.outputs["out_port"].description
    assert schema.properties["amount"].default == 1
    with pytest.raises(pp.SchemaError, match="not a registered node type"):
        pp.node_type_schema(Transform)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_override", [False, True])
async def test_transform_failure_has_ordinary_node_context(
    sink: tuple[pp.NodeDeclaration, list[int]], missing_override: bool
) -> None:
    original = ValueError("transform exploded")

    @pp.node_type
    class Broken(Transform[int, int]):
        async def transform(self, value: int) -> int:
            raise original

    @pp.node_type
    class Missing(Transform[int, int]):
        pass

    destination, _ = sink
    failing = declare(Missing if missing_override else Broken)
    async with asyncio.timeout(2):
        with pytest.raises(ExceptionGroup) as caught:
            await pp.run(declare(Source) | failing | destination)
    errors = [
        error
        for error in caught.value.exceptions
        if isinstance(error, pp.NodeExecutionError) and error.node_id == failing.id
    ]
    assert len(errors) == 1
    error = errors[0]
    assert error.node_type is failing.node_type
    assert error.node_type_name == failing.node_type.__name__
    assert failing.id in str(error) and error.node_type_name in str(error)
    if missing_override:
        assert isinstance(error.__cause__, NotImplementedError)
        assert "implement transform()" in str(error.__cause__)
    else:
        assert error.__cause__ is original


@pytest.mark.asyncio
async def test_print_preserves_typed_stream(
    sink: tuple[pp.NodeDeclaration, list[int]], capsys: pytest.CaptureFixture[str]
) -> None:
    from pyrophone.nodes import Print

    @pp.node_type
    class PrintInt(Print[int]):
        pass

    destination, values = sink
    async with asyncio.timeout(2):
        await pp.run(declare(Source) | declare(PrintInt) | destination)
    assert values == [1, 2, 3]
    assert capsys.readouterr().out == "1\n2\n3\n"
    schema = pp.node_type_schema(PrintInt)
    assert schema.inputs["in_port"].type is int
    assert schema.outputs["out_port"].type is int


@pytest.mark.asyncio
async def test_print_bytes_preserves_payload_and_flushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    from pyrophone.nodes import PrintBytes

    class Stdout(io.StringIO):
        flushes = 0

        def flush(self) -> None:
            self.flushes += 1
            super().flush()

    stdout = Stdout()
    monkeypatch.setattr("sys.stdout", stdout)
    payloads = [b'{"count":1,"label":"demo"}', b"\x00\xff"]
    received: list[bytes] = []

    @pp.node_type
    class Emit(pp.Node):
        out_port = pp.Output[bytes]()

        async def run(self) -> None:
            for value in payloads:
                await self.out_port.send(value)

    @pp.node_type
    class Collect(pp.Node):
        in_port = pp.Input[bytes]()

        async def run(self) -> None:
            async for value in self.in_port:
                received.append(value)

    async with asyncio.timeout(2):
        await pp.run(declare(Emit) | declare(PrintBytes) | declare(Collect))
    assert all(
        actual is original for actual, original in zip(received, payloads, strict=True)
    )
    assert stdout.getvalue() == "".join(f"{value!r}\n" for value in payloads)
    assert stdout.flushes == len(payloads)


@pytest.mark.asyncio
async def test_identity_preserves_object_identity_and_stream_order() -> None:
    from pyrophone.nodes import Identity

    payloads: list[object] = [{"nested": [1, 2]}, None, b"\x00\xff"]
    received: list[object] = []

    @pp.node_type
    class IdentityObject(Identity[object]):
        pass

    @pp.node_type
    class Emit(pp.Node):
        out_port = pp.Output[object]()

        async def run(self) -> None:
            for payload in payloads:
                await self.out_port.send(payload)

    @pp.node_type
    class Collect(pp.Node):
        in_port = pp.Input[object]()

        async def run(self) -> None:
            async for value in self.in_port:
                received.append(value)

    await pp.run_async(declare(Emit) | declare(IdentityObject) | declare(Collect))
    assert len(received) == len(payloads)
    assert all(
        actual is expected for actual, expected in zip(received, payloads, strict=True)
    )
    assert received == [{"nested": [1, 2]}, None, b"\x00\xff"]


def test_identity_bytes_has_single_concrete_input_and_output() -> None:
    from pyrophone.script import IdentityBytes

    schema = pp.node_type_schema(IdentityBytes)
    assert list(schema.inputs) == ["in_port"]
    assert list(schema.outputs) == ["out_port"]
    assert schema.inputs["in_port"].type is bytes
    assert schema.outputs["out_port"].type is bytes
