"""JSON transforms expose decoded values while retaining byte-oriented ports."""

import asyncio
import json
from collections.abc import Callable
from typing import cast

import pytest

from pyrophone import (
    Input,
    Node,
    NodeDeclaration,
    Output,
    node_type,
    node_type_schema,
    run,
)
from pyrophone.nodes import JSONTransform, JSONValue


async def apply_transform(cls: type[Node], payload: bytes) -> bytes:
    received: list[bytes] = []

    @node_type
    class Source(Node):
        out_port = Output[bytes]()

        async def run(self) -> None:
            await self.out_port.send(payload)

    @node_type
    class Sink(Node):
        in_port = Input[bytes]()

        async def run(self) -> None:
            async for value in self.in_port:
                received.append(value)

    def declare(node: type[Node]) -> NodeDeclaration:
        return cast(Callable[[], NodeDeclaration], node)()

    async with asyncio.timeout(2):
        await run(declare(Source) | declare(cls) | declare(Sink))
    assert len(received) == 1
    return received[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [{"nested": [None, True, "café"]}, [1, 2], "text", 3.5, False, None]
)
async def test_hook_receives_decoded_value_and_result_is_encoded(
    value: JSONValue,
) -> None:
    seen: list[JSONValue] = []

    @node_type
    class Wrap(JSONTransform):
        async def transform_json(self, value: JSONValue) -> JSONValue:
            seen.append(value)
            return {"original": value}

    result = await apply_transform(Wrap, json.dumps(value).encode())
    assert seen == [value]
    assert json.loads(result) == {"original": value}
    schema = node_type_schema(Wrap)
    assert schema.inputs["in_port"].type is bytes
    assert schema.outputs["out_port"].type is bytes


@pytest.mark.asyncio
async def test_invalid_json_fails_before_hook() -> None:
    called = False

    @node_type
    class Identity(JSONTransform):
        async def transform_json(self, value: JSONValue) -> JSONValue:
            nonlocal called
            called = True
            return value

    with pytest.raises(ExceptionGroup) as caught:
        await apply_transform(Identity, b"not json")
    assert not called
    assert any(
        isinstance(error.__cause__, json.JSONDecodeError)
        for error in caught.value.exceptions
    )


@pytest.mark.asyncio
async def test_missing_override_has_clear_error() -> None:
    @node_type
    class Missing(JSONTransform):
        pass

    with pytest.raises(ExceptionGroup) as caught:
        await apply_transform(Missing, b"{}")
    assert any(
        isinstance(error.__cause__, NotImplementedError)
        and "transform_json" in str(error.__cause__)
        for error in caught.value.exceptions
    )


@pytest.mark.asyncio
async def test_nonfinite_output_is_rejected() -> None:
    @node_type
    class Nonfinite(JSONTransform):
        async def transform_json(self, value: JSONValue) -> JSONValue:
            return float("inf")

    with pytest.raises(ExceptionGroup) as caught:
        await apply_transform(Nonfinite, b"null")
    assert any(
        isinstance(error.__cause__, ValueError) for error in caught.value.exceptions
    )
