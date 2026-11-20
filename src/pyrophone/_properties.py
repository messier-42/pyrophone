"""Read-only configuration descriptors used by node authors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never, cast, overload

from ._exceptions import SchemaError
from ._schema import _MISSING, _Missing

if TYPE_CHECKING:
    from ._node import Node


class Property[T]:
    """Declare a typed property; omitting default makes it required.

    Values are bound separately for each runtime instance. Configuration is
    shallowly read-only: callers may still mutate a mutable value's contents.
    """

    def __init__(
        self,
        *,
        default: T | _Missing = _MISSING,
        title: str | None = None,
        description: str | None = None,
        minimum: int | float | None = None,
        maximum: int | float | None = None,
        step: int | float | None = None,
    ) -> None:
        self.default = default
        self.title = title
        self.description = description
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
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
    def __get__(
        self, instance: None, owner: type[Node] | None = None
    ) -> Property[T]: ...

    @overload
    def __get__(self, instance: Node, owner: type[Node] | None = None) -> T: ...

    def __get__(
        self, instance: Node | None, owner: type[Node] | None = None
    ) -> Property[T] | T:
        if instance is None:
            return self
        return cast(T, instance._configuration[self._name])

    def __set__(self, instance: Node, value: Never) -> Never:
        raise AttributeError(f"{self._name} is read-only configuration")
