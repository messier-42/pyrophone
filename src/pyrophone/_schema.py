"""Immutable declaration metadata and shared runtime type operations."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from functools import reduce
from operator import or_
from types import MappingProxyType, UnionType
from typing import Any, TypeVar, Union, get_args, get_origin

from ._exceptions import ConfigurationError, SchemaError


class _Missing(Enum):
    TOKEN = auto()


_MISSING = _Missing.TOKEN


@dataclass(frozen=True)
class PropertySchema:
    name: str
    type: object
    default: object = _MISSING
    title: str | None = None
    description: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None

    @property
    def required(self) -> bool:
        return self.default is _MISSING


@dataclass(frozen=True)
class PortSchema:
    name: str
    type: object
    description: str | None = None
    default: bool = False


@dataclass(frozen=True)
class NodeTypeSchema:
    name: str
    description: str | None
    properties: Mapping[str, PropertySchema]
    inputs: Mapping[str, PortSchema]
    outputs: Mapping[str, PortSchema]

    def __post_init__(self) -> None:
        # Own each mapping: subsequent changes to a caller's dictionary cannot
        # mutate a registered schema.
        object.__setattr__(self, "properties", MappingProxyType(dict(self.properties)))
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))


_CONTAINERS = (list, dict, tuple, set, frozenset)


def substitute_type(spec: object, substitutions: Mapping[TypeVar, object]) -> object:
    """Resolve type variables recursively, preserving parameterized containers."""
    if isinstance(spec, TypeVar):
        return substitutions.get(spec, spec)
    origin = get_origin(spec)
    if origin not in (*_CONTAINERS, Union, UnionType):
        # Leave unsupported forms intact so validate_type reports a contextual
        # SchemaError rather than leaking an error from alias reconstruction.
        return spec
    args = tuple(substitute_type(arg, substitutions) for arg in get_args(spec))
    if origin in (Union, UnionType):
        # Dynamic type construction is intentionally confined to this boundary.
        return _make_union(args)
    return _parameterize(spec, origin, args)


def _make_union(args: tuple[object, ...]) -> object:
    dynamic_args: Any = args
    return reduce(or_, dynamic_args)


def _parameterize(spec: object, origin: object, args: tuple[object, ...]) -> object:
    # typing aliases expose copy_with; builtin GenericAlias uses subscription.
    dynamic_spec: Any = spec
    dynamic_origin: Any = origin
    if hasattr(spec, "copy_with"):
        return dynamic_spec.copy_with(args)
    return dynamic_origin[args]


def validate_type(spec: object, name: str = "type") -> None:
    """Reject types for which value validation has no well-defined behavior."""
    if spec is Any:
        return
    if isinstance(spec, TypeVar):
        raise SchemaError(f"{name}: unresolved type variable {spec}")
    origin = get_origin(spec)
    args = get_args(spec)
    if origin in (Union, UnionType):
        for arg in args:
            validate_type(arg, name)
        return
    if origin in _CONTAINERS:
        if origin is dict and len(args) != 2:
            raise SchemaError(f"{name}: unsupported dictionary type {spec}")
        if origin in (list, set, frozenset) and len(args) != 1:
            raise SchemaError(f"{name}: unsupported container type {spec}")
        if (
            origin is tuple
            and Ellipsis in args
            and not (len(args) == 2 and args[1] is Ellipsis)
        ):
            raise SchemaError(f"{name}: unsupported tuple type {spec}")
        for index, arg in enumerate(args):
            if origin is tuple and index == 1 and arg is Ellipsis:
                continue
            validate_type(arg, name)
        return
    if origin is None and isinstance(spec, type):
        if getattr(spec, "_is_protocol", False):
            raise SchemaError(f"{name}: unsupported protocol type {spec}")
        try:
            isinstance(None, spec)
        except TypeError as error:
            raise SchemaError(f"{name}: unsupported runtime type {spec}") from error
        return
    raise SchemaError(f"{name}: unsupported type {spec!r}")


def _matches(value: object, spec: object) -> bool:
    if spec is Any:
        return True
    origin = get_origin(spec)
    args = get_args(spec)
    if origin in (Union, UnionType):
        return any(_matches(value, arg) for arg in args)
    if origin is dict:
        return isinstance(value, dict) and all(
            _matches(key, args[0]) and _matches(item, args[1])
            for key, item in value.items()
        )
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_matches(item, args[0]) for item in value)
        return len(value) == len(args) and all(
            _matches(item, arg) for item, arg in zip(value, args, strict=True)
        )
    if origin in (list, set, frozenset):
        return isinstance(value, origin) and all(
            _matches(item, args[0]) for item in value
        )
    return isinstance(spec, type) and isinstance(value, spec)


def validate_value(value: object, spec: object, name: str) -> None:
    validate_type(spec, name)
    if not _matches(value, spec):
        raise ConfigurationError(f"{name}: expected {spec}, got {type(value).__name__}")


def is_type_compatible(source: object, destination: object) -> bool:
    """Conservatively decide whether every source value fits the destination."""
    validate_type(source, "source")
    validate_type(destination, "destination")
    if source == destination or destination is Any:
        return True
    if source is Any:
        return False
    source_origin, destination_origin = get_origin(source), get_origin(destination)
    if source_origin in (Union, UnionType):
        return all(is_type_compatible(arg, destination) for arg in get_args(source))
    if destination_origin in (Union, UnionType):
        return any(is_type_compatible(source, arg) for arg in get_args(destination))
    # Parameterized containers are invariant. A container itself may still flow
    # to an ordinary superclass such as object.
    if destination_origin is not None:
        return False
    nominal_source = source_origin or source
    return (
        isinstance(nominal_source, type)
        and isinstance(destination, type)
        and issubclass(nominal_source, destination)
    )


def validate_property(value: object, schema: PropertySchema) -> None:
    validate_value(value, schema.type, schema.name)
    if isinstance(value, (int, float)):
        if schema.minimum is not None and value < schema.minimum:
            raise ConfigurationError(f"{schema.name}: below minimum {schema.minimum}")
        if schema.maximum is not None and value > schema.maximum:
            raise ConfigurationError(f"{schema.name}: above maximum {schema.maximum}")
