"""Port declarations and the typed interfaces seen by running nodes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Never, Protocol, cast, overload

from ._exceptions import SchemaError

if TYPE_CHECKING:
    from ._node import Node


class InputPort[T](Protocol):
    async def recv(self) -> T:
        """Receive the next value; cancellation follows the runtime task."""
        ...

    async def close(self) -> None:
        """Stop accepting values, waking any blocked senders."""
        ...

    def __aiter__(self) -> AsyncIterator[T]: ...


class OutputPort[T](Protocol):
    async def send(self, value: T) -> None:
        """Wait until a receiver accepts the value, without processing acknowledgement."""
        ...

    async def close(self) -> None:
        """Announce end of stream and reject unaccepted sends."""
        ...


class Input[T]:
    def __init__(
        self, *, description: str | None = None, default: bool = False
    ) -> None:
        self.description = description
        self.default = default
        self._name = ""
        self._owner: type[Node] | None = None

    def __set_name__(self, owner: type[Node], name: str) -> None:
        if self._owner is not None and (owner is not self._owner or name != self._name):
            raise SchemaError(
                f"{name}: cannot reuse declaration {self._owner.__name__}.{self._name}"
            )
        self._owner = owner
        self._name = name

    @overload
    def __get__(self, instance: None, owner: type[Node] | None = None) -> Input[T]: ...

    @overload
    def __get__(
        self, instance: Node, owner: type[Node] | None = None
    ) -> InputPort[T]: ...

    def __get__(
        self, instance: Node | None, owner: type[Node] | None = None
    ) -> Input[T] | InputPort[T]:
        if instance is None:
            return self
        return cast(InputPort[T], instance._inputs[self._name])

    def __set__(self, instance: Node, value: Never) -> Never:
        raise AttributeError(f"{self._name} is a read-only input binding")


class Output[T]:
    def __init__(
        self, *, description: str | None = None, default: bool = False
    ) -> None:
        self.description = description
        self.default = default
        self._name = ""
        self._owner: type[Node] | None = None

    def __set_name__(self, owner: type[Node], name: str) -> None:
        if self._owner is not None and (owner is not self._owner or name != self._name):
            raise SchemaError(
                f"{name}: cannot reuse declaration {self._owner.__name__}.{self._name}"
            )
        self._owner = owner
        self._name = name

    @overload
    def __get__(self, instance: None, owner: type[Node] | None = None) -> Output[T]: ...

    @overload
    def __get__(
        self, instance: Node, owner: type[Node] | None = None
    ) -> OutputPort[T]: ...

    def __get__(
        self, instance: Node | None, owner: type[Node] | None = None
    ) -> Output[T] | OutputPort[T]:
        if instance is None:
            return self
        return cast(OutputPort[T], instance._outputs[self._name])

    def __set__(self, instance: Node, value: Never) -> Never:
        raise AttributeError(f"{self._name} is a read-only output binding")
