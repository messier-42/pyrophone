"""Node registration and the private runtime allocation boundary."""

import inspect
from collections.abc import Mapping
from copy import deepcopy
from math import isfinite
from types import MappingProxyType, UnionType
from typing import TYPE_CHECKING, TypeVar, Union, cast, get_args, get_origin

from ._exceptions import ConfigurationError, SchemaError
from ._inspection import Printable, node_details
from ._ports import Input, Output
from ._properties import Property
from ._schema import (
    NodeTypeSchema,
    PortSchema,
    PropertySchema,
    substitute_type,
    validate_property,
    validate_type,
)

if TYPE_CHECKING:
    from ._graph import NodeDeclaration


class _NodeMeta(type):
    def __call__(cls, /, **configuration: object) -> "NodeDeclaration":
        from ._graph import NodeDeclaration

        return NodeDeclaration(cast(type[Node], cls), configuration)


class Node(Printable, metaclass=_NodeMeta):
    """Base for node implementations. Runtime construction is framework-owned."""

    _configuration: Mapping[str, object]
    _inputs: Mapping[str, object]
    _outputs: Mapping[str, object]

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"

    def _describe(self) -> str:
        return node_details(
            type(self), self._configuration, node_type_schema(type(self))
        )

    async def run(self) -> None:
        raise NotImplementedError("Node subclasses must implement run()")


def _generic_contexts(cls: type[Node]) -> dict[type, dict[TypeVar, object]]:
    contexts: dict[type, dict[TypeVar, object]] = {}

    def visit(current: type, context: dict[TypeVar, object]) -> None:
        if current in contexts:
            return
        contexts[current] = context
        declared_bases = current.__dict__.get("__orig_bases__", current.__bases__)
        for base in declared_bases:
            origin = get_origin(base) or base
            if not isinstance(origin, type):
                continue
            parameters = getattr(origin, "__type_params__", ()) or getattr(
                origin, "__parameters__", ()
            )
            arguments = get_args(base)
            resolved = {
                parameter: substitute_type(argument, context)
                for parameter, argument in zip(parameters, arguments, strict=False)
                if isinstance(parameter, TypeVar)
            }
            visit(origin, resolved)

    visit(cls, {})
    return contexts


def node_type[N: Node](cls: type[N]) -> type[N]:
    """Register a class's immutable schema without constructing an instance."""
    if not issubclass(cls, Node):
        raise SchemaError("node_type requires a Node subclass")
    properties: dict[str, PropertySchema] = {}
    inputs: dict[str, PortSchema] = {}
    outputs: dict[str, PortSchema] = {}
    contexts = _generic_contexts(cls)
    seen: set[str] = set()
    for owner in cls.__mro__:
        for name, declaration in vars(owner).items():
            if name in seen:
                continue
            seen.add(name)
            if not isinstance(declaration, (Property, Input, Output)):
                continue
            arguments = get_args(getattr(declaration, "__orig_class__", None))
            if len(arguments) != 1:
                raise SchemaError(f"{name}: an explicit generic type is required")
            spec = substitute_type(arguments[0], contexts.get(owner, {}))
            validate_type(spec, name)
            if isinstance(declaration, Property):
                prop = PropertySchema(
                    name=name,
                    type=spec,
                    default=deepcopy(declaration.default),
                    title=declaration.title,
                    description=declaration.description,
                    minimum=declaration.minimum,
                    maximum=declaration.maximum,
                    step=declaration.step,
                )
                _validate_property_schema(prop)
                properties[name] = prop
            else:
                ports = inputs if isinstance(declaration, Input) else outputs
                if declaration.default and any(port.default for port in ports.values()):
                    raise SchemaError(
                        f"{name}: multiple default ports in one direction"
                    )
                ports[name] = PortSchema(
                    name, spec, declaration.description, declaration.default
                )
    cls._node_type_schema = NodeTypeSchema(  # type: ignore[attr-defined]
        cls.__name__, inspect.getdoc(cls), properties, inputs, outputs
    )
    return cls


def _validate_property_schema(schema: PropertySchema) -> None:
    for name in ("minimum", "maximum", "step"):
        value = getattr(schema, name)
        if value is None:
            continue
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or (isinstance(value, float) and not isfinite(value))
        ):
            raise SchemaError(f"{schema.name}: {name} must be a finite number")
        if not _numeric_type(schema.type):
            raise SchemaError(f"{schema.name}: {name} requires a numeric property")
    if schema.minimum is not None and schema.maximum is not None:
        if schema.minimum > schema.maximum:
            raise SchemaError(f"{schema.name}: minimum exceeds maximum")
    if schema.step is not None and schema.step <= 0:
        raise SchemaError(f"{schema.name}: step must be positive")
    if not schema.required:
        try:
            validate_property(schema.default, schema)
        except ConfigurationError as error:
            raise SchemaError(f"{schema.name}: invalid default: {error}") from error


def _numeric_type(spec: object) -> bool:
    if get_origin(spec) in (Union, UnionType):
        types = [arg for arg in get_args(spec) if arg is not type(None)]
        return bool(types) and all(_numeric_type(arg) for arg in types)
    return (
        isinstance(spec, type) and spec is not bool and issubclass(spec, (int, float))
    )


def node_type_schema(cls: type[Node]) -> NodeTypeSchema:
    """Return this class's schema; subclasses require their own registration."""
    schema = vars(cls).get("_node_type_schema")
    if not isinstance(schema, NodeTypeSchema):
        raise SchemaError(f"{cls.__name__} is not a registered node type")
    return schema


def _resolve_configuration(
    schema: NodeTypeSchema, configuration: Mapping[str, object]
) -> dict[str, object]:
    unknown = configuration.keys() - schema.properties.keys()
    if unknown:
        raise ConfigurationError(f"unknown properties: {', '.join(sorted(unknown))}")
    values: dict[str, object] = {}
    for name, prop in schema.properties.items():
        if name in configuration:
            value = configuration[name]
        elif prop.required:
            raise ConfigurationError(f"{name}: required property is missing")
        else:
            value = prop.default
        validate_property(value, prop)
        values[name] = deepcopy(value)
    return values


def _bind_node[N: Node](
    cls: type[N],
    configuration: Mapping[str, object],
    inputs: Mapping[str, object],
    outputs: Mapping[str, object],
) -> N:
    """Allocate a live node and bind state before its no-argument initializer.

    Graph declarations must never use this path. Each invocation owns fresh
    configuration and port mappings; endpoints themselves belong to the runtime.
    """
    schema = node_type_schema(cls)
    values = _resolve_configuration(schema, configuration)
    for kind, supplied, expected in (
        ("input", inputs, schema.inputs),
        ("output", outputs, schema.outputs),
    ):
        if supplied.keys() != expected.keys():
            raise ConfigurationError(f"{kind} bindings must match declared ports")
    instance = object.__new__(cls)
    instance._configuration = MappingProxyType(values)
    instance._inputs = MappingProxyType(dict(inputs))
    instance._outputs = MappingProxyType(dict(outputs))
    instance.__init__()  # type: ignore[misc]
    return instance
