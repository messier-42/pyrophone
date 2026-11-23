"""Reusable node implementations built on the public component model."""

import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import ClassVar, overload

from ._node import Node, node_type
from ._ports import Input, Output

type JSONValue = (
    bool | int | float | str | list[JSONValue] | dict[str, JSONValue] | None
)


class Source[T](Node):
    """Send the values from an async generator through one output port.

    Override produce() and register a concrete subclass with node_type.
    The next value is requested after the current send is accepted.
    """

    out_port = Output[T](description="Produced values.")

    async def run(self) -> None:
        async with aclosing(self.produce()) as values:
            async for value in values:
                await self.out_port.send(value)

    def produce(self) -> AsyncGenerator[T, None]:
        raise NotImplementedError("Source subclasses must implement produce()")


class Sink[T](Node):
    """Consume values from one input port in stream order.

    Override consume() and register a concrete subclass with node_type.
    Each call finishes before the next input is received.
    """

    in_port = Input[T](description="Values to consume.")

    async def run(self) -> None:
        async for value in self.in_port:
            await self.consume(value)

    async def consume(self, value: T) -> None:
        raise NotImplementedError("Sink subclasses must implement consume()")


class Transform[InputT, OutputT](Node):
    """Transform each input value into one output value, in stream order.

    Override transform() and register a concrete subclass with node_type.
    """

    in_port = Input[InputT](description="Values to transform.")
    out_port = Output[OutputT](description="Transformed values.")

    async def run(self) -> None:
        async for value in self.in_port:
            result = await self.transform(value)
            await self.out_port.send(result)

    async def transform(self, value: InputT) -> OutputT:
        raise NotImplementedError("Transform subclasses must implement transform()")


class Identity[T](Transform[T, T]):
    """Forward each value unchanged, preserving its type and object identity.

    Register a concrete subclass, such as Identity[int], with node_type.
    """

    async def transform(self, value: T) -> T:
        return value


@node_type
class IdentityBytes(Identity[bytes]):
    """Pass byte payloads through unchanged."""


class Print[T](Transform[T, T]):
    """Print each value to stdout and forward it unchanged.

    Uses Python's normal print formatting and flushes each line immediately.
    Register a concrete subclass such as Print[int] with node_type.
    """

    async def transform(self, value: T) -> T:
        print(value, flush=True)
        return value


@node_type
class PrintBytes(Print[bytes]):
    """Print byte payloads (including the b prefix) without decoding them."""


@node_type
class PrintText(Transform[str | bytes, str | bytes]):
    """Print text or UTF-8 bytes and forward the original value unchanged.

    Invalid UTF-8 prints as a bytes repr. Each print flushes stdout immediately.
    The graph infers the output type from the connected upstream port.
    """

    _output_type_sources: ClassVar[dict[str, str]] = {"out_port": "in_port"}

    @overload
    async def transform(self, value: str) -> str: ...

    @overload
    async def transform(self, value: bytes) -> bytes: ...

    async def transform(self, value: str | bytes) -> str | bytes:
        text = value
        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError:
                text = repr(value)
        print(text, flush=True)
        return value


class JSONTransform(Transform[bytes, bytes]):
    """Decode JSON, transform its value, and encode the result as UTF-8 bytes.

    Override transform_json(); ports remain byte-oriented for direct connection
    to transports such as MQTT. Encoding uses compact JSON with Unicode text
    preserved and rejects non-finite numbers. Codec and hook errors propagate
    through the normal node failure contract.
    """

    async def transform(self, payload: bytes) -> bytes:
        value: JSONValue = json.loads(payload)
        result = await self.transform_json(value)
        return json.dumps(
            result, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")

    async def transform_json(self, value: JSONValue) -> JSONValue:
        raise NotImplementedError(
            "JSONTransform subclasses must implement transform_json()"
        )
