"""JSON byte-stream filtering with the optional PyPI ``jq`` binding."""

import json
from collections.abc import Iterable
from importlib import import_module
from typing import Protocol, cast

from ._node import Node, node_type
from ._ports import Input, Output
from ._properties import Property
from .nodes import JSONValue

__all__ = ["JQ"]


class _Program(Protocol):
    def input_value(self, value: JSONValue) -> Iterable[JSONValue]: ...


def _compile(program: str) -> _Program:
    try:
        jq = import_module("jq")
    except ModuleNotFoundError as error:
        if error.name != "jq":
            raise
        raise ImportError(
            "JQ requires optional dependencies: pip install 'Pyrophone[jq]'"
        ) from error
    return cast(_Program, jq.compile(program))


@node_type
class JQ(Node):
    """Apply a jq program to each JSON payload, emitting zero or more results.

    Each input is one complete JSON value encoded as bytes. Results are emitted
    individually as compact UTF-8 JSON, preserving jq order and backpressure.
    Unlike the one-to-one Transform base, jq can filter or expand messages.
    Compilation and evaluation use synchronous bindings on the runtime loop.
    """

    expr = Property[str](
        title="jq expression",
        description=(
            "jq expression applied to each JSON message, for example .count += 1. "
            "Live changes take effect on the next input message."
        ),
    )
    in_port = Input[bytes](description="One complete JSON value per payload.")
    out_port = Output[bytes](description="One JSON-encoded payload per jq result.")

    async def run(self) -> None:
        source = self.expr
        compiled = _compile(source)
        async for payload in self.in_port:
            current = self.expr
            if current != source:
                compiled = _compile(current)
                source = current
            value: JSONValue = json.loads(payload)
            for result in compiled.input_value(value):
                encoded = json.dumps(
                    result, separators=(",", ":"), ensure_ascii=False, allow_nan=False
                ).encode("utf-8")
                await self.out_port.send(encoded)
