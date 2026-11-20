from collections.abc import AsyncIterator

import pytest

from pyrophone import (
    ConfigurationError,
    Input,
    Node,
    Output,
    Property,
    SchemaError,
    node_type,
)
from pyrophone._node import _bind_node


@node_type
class Configured(Node):
    amount = Property[int](default=1, minimum=-100, maximum=100, step=1)
    name = Property[str]()
    values = Property[list[int]](default=[])
    in_port = Input[int]()
    out_port = Output[int]()

    def __init__(self) -> None:
        self.initializations = 1
        self.initial_amount = self.amount
        self.initial_input = self.in_port


class InputBuffer:
    async def close(self) -> None:
        pass

    async def recv(self) -> int:
        return 4

    async def __aiter__(self) -> AsyncIterator[int]:
        yield await self.recv()


class OutputBuffer:
    async def close(self) -> None:
        pass

    def __init__(self) -> None:
        self.values: list[int] = []

    async def send(self, value: int) -> None:
        self.values.append(value)


def test_private_binding_initializes_after_config_and_copies_values() -> None:
    values = [2]
    incoming, outgoing = InputBuffer(), OutputBuffer()
    one = _bind_node(
        Configured,
        {"name": "one", "amount": 3, "values": values},
        {"in_port": incoming},
        {"out_port": outgoing},
    )
    two = _bind_node(
        Configured,
        {"name": "two"},
        {"in_port": InputBuffer()},
        {"out_port": OutputBuffer()},
    )
    three = _bind_node(
        Configured,
        {"name": "three"},
        {"in_port": InputBuffer()},
        {"out_port": OutputBuffer()},
    )
    assert one.initializations == 1
    assert one.initial_amount == 3
    assert one.initial_input is incoming
    assert one.out_port is outgoing
    assert two.in_port is not incoming
    one.values.append(3)
    two.values.append(5)
    assert values == [2]
    assert three.values == []
    assert two.amount == 1
    with pytest.raises(AttributeError, match="read-only"):
        setattr(one, "amount", 5)  # noqa: B010 - runtime read-only check
    with pytest.raises(AttributeError, match="read-only"):
        setattr(one, "in_port", incoming)  # noqa: B010 - runtime read-only check
    with pytest.raises(AttributeError, match="read-only"):
        setattr(one, "out_port", outgoing)  # noqa: B010 - runtime read-only check


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({}, "name.*required"),
        ({"name": "x", "other": 2}, "unknown.*other"),
        ({"name": 2}, "name.*str"),
        ({"name": "x", "amount": -101}, "amount.*minimum"),
        ({"name": "x", "amount": 101}, "amount.*maximum"),
    ],
)
def test_invalid_configuration(config: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        _bind_node(
            Configured, config, {"in_port": InputBuffer()}, {"out_port": OutputBuffer()}
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {"default": "wrong"},
        {"default": -1, "minimum": 0},
        {"default": 11, "maximum": 10},
        {"minimum": 2, "maximum": 1},
        {"step": 0},
        {"step": -1},
    ],
)
def test_invalid_property_declarations(metadata: dict[str, object]) -> None:
    class Invalid(Node):
        amount = Property[int](**metadata)  # type: ignore[arg-type]

    with pytest.raises(SchemaError, match="amount"):
        node_type(Invalid)


@pytest.mark.asyncio
async def test_bound_endpoints_work() -> None:
    outgoing = OutputBuffer()
    node = _bind_node(
        Configured, {"name": "x"}, {"in_port": InputBuffer()}, {"out_port": outgoing}
    )
    async for value in node.in_port:
        await node.out_port.send(value + node.amount)
    assert outgoing.values == [5]


@pytest.mark.parametrize(
    "metadata",
    [
        {"minimum": "low"},
        {"maximum": "high"},
        {"step": "step"},
        {"minimum": float("nan")},
        {"step": float("inf")},
    ],
)
def test_invalid_numeric_metadata_fails_clearly(metadata: dict[str, object]) -> None:
    class Invalid(Node):
        amount = Property[int](**metadata)  # type: ignore[arg-type]

    with pytest.raises(SchemaError, match="amount"):
        node_type(Invalid)


def test_numeric_metadata_requires_a_numeric_property() -> None:
    class Invalid(Node):
        name = Property[str](minimum=1)

    with pytest.raises(SchemaError, match=r"name.*numeric"):
        node_type(Invalid)


@pytest.mark.parametrize(
    ("inputs", "outputs"),
    [
        ({}, {"out_port": OutputBuffer()}),
        (
            {"in_port": InputBuffer(), "extra": InputBuffer()},
            {"out_port": OutputBuffer()},
        ),
        ({"in_port": InputBuffer()}, {}),
    ],
)
def test_bindings_must_match_schema(
    inputs: dict[str, object], outputs: dict[str, object]
) -> None:
    with pytest.raises(ConfigurationError, match="bindings"):
        _bind_node(Configured, {"name": "node"}, inputs, outputs)


@pytest.mark.parametrize("field", ["amount", "in_port", "out_port"])
def test_descriptor_reuse_cannot_corrupt_existing_class(field: str) -> None:
    declaration = vars(Configured)[field]
    with pytest.raises(SchemaError, match="reuse"):

        class Reused(Node):
            other = declaration

    incoming, outgoing = InputBuffer(), OutputBuffer()
    node = _bind_node(
        Configured,
        {"name": "intact", "amount": 3},
        {"in_port": incoming},
        {"out_port": outgoing},
    )
    assert node.amount == 3
    assert node.in_port is incoming
    assert node.out_port is outgoing
