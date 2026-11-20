from dataclasses import FrozenInstanceError
from types import GenericAlias
from typing import Any, Literal, TypeVar

import pytest

from pyrophone import (
    Input,
    Node,
    Output,
    Property,
    SchemaError,
    node_type,
    node_type_schema,
)
from pyrophone._schema import is_type_compatible, validate_type, validate_value


@node_type
class Example(Node):
    """An example node.

    More detailed documentation.
    """

    amount = Property[int](
        default=1,
        title="Amount",
        description="First paragraph.\n\nSecond paragraph.",
        minimum=-100,
        maximum=100,
        step=1,
    )
    name = Property[str]()
    in_port = Input[int](description="Incoming numbers", default=True)
    out_port = Output[int](description="Outgoing numbers", default=True)


def test_schema_preserves_explicit_types_and_metadata() -> None:
    schema = node_type_schema(Example)
    assert schema.name == "Example"
    assert schema.description == "An example node.\n\nMore detailed documentation."
    amount = schema.properties["amount"]
    assert amount.type is int
    assert amount.default == 1
    assert not amount.required
    assert (amount.title, amount.description) == (
        "Amount",
        "First paragraph.\n\nSecond paragraph.",
    )
    assert (amount.minimum, amount.maximum, amount.step) == (-100, 100, 1)
    assert schema.properties["name"].required
    assert schema.inputs["in_port"].type is int
    assert schema.inputs["in_port"].description == "Incoming numbers"
    assert schema.inputs["in_port"].default
    assert schema.outputs["out_port"].default
    with pytest.raises(TypeError):
        schema.properties["bad"] = amount  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        setattr(amount, "title", "Changed")  # noqa: B010 - exercise frozen metadata


def test_inheritance_follows_python_mro_and_specializes_generic_helpers() -> None:
    class Base[T](Node):
        values = Property[list[T]](default=[])
        in_port = Input[T]()
        out_port = Output[T]()

    class Intermediate[U](Base[list[U]]):
        pass

    @node_type
    class Concrete(Intermediate[int]):
        pass

    schema = node_type_schema(Concrete)
    assert schema.inputs["in_port"].type == list[int]
    assert schema.outputs["out_port"].type == list[int]
    assert schema.properties["values"].type == list[list[int]]

    class Left(Node):
        amount = Property[int](default=1)

    class Right(Node):
        amount = Property[int](default=2)
        other = Output[str]()

    @node_type
    class Both(Left, Right):
        pass

    assert node_type_schema(Both).properties["amount"].default == 1
    assert node_type_schema(Both).outputs["other"].type is str

    @node_type
    class Override(Both):
        amount = Property[int](default=3)

    assert node_type_schema(Override).properties["amount"].default == 3
    assert node_type_schema(Both).properties["amount"].default == 1


def test_registration_rejects_missing_explicit_type_and_unresolved_types() -> None:
    class Untyped(Node):
        amount = Property(default=1)

    with pytest.raises(SchemaError, match=r"amount.*explicit"):
        node_type(Untyped)

    class GenericNode[T](Node):
        item = Input[T]()

    with pytest.raises(SchemaError, match=r"item.*unresolved"):
        node_type(GenericNode)

    class Unsupported(Node):
        item = Input[Literal[1]]()

    with pytest.raises(SchemaError, match=r"item.*unsupported"):
        node_type(Unsupported)


@pytest.mark.parametrize("direction", [Input[int], Output[int]])
def test_only_one_default_port_per_direction(
    direction: type[Input[int]] | type[Output[int]],
) -> None:
    class Duplicate(Node):
        first = direction(default=True)
        second = direction(default=True)

    with pytest.raises(SchemaError, match="default"):
        node_type(Duplicate)


def test_schema_requires_explicit_registration_even_for_subclasses() -> None:
    class Child(Example):
        pass

    with pytest.raises(SchemaError, match="registered"):
        node_type_schema(Child)


@pytest.mark.parametrize(
    ("expected", "valid", "invalid"),
    [
        (int, 2, "2"),
        (int | None, None, "2"),
        (list[int], [1, 2], ["2"]),
        (dict[str, int], {"a": 1}, {1: "a"}),
        (tuple[int, str], (1, "a"), (1, 2)),
        (tuple[int, ...], (1, 2), (1, "a")),
        (set[int], {1}, {"a"}),
        (frozenset[str], frozenset({"a"}), frozenset({1})),
    ],
)
def test_supported_runtime_values(
    expected: object, valid: object, invalid: object
) -> None:
    validate_type(expected)
    validate_value(valid, expected, "value")
    with pytest.raises(ValueError, match="value"):
        validate_value(invalid, expected, "value")


def test_any_and_nominal_classes() -> None:
    class Parent:
        pass

    class Child(Parent):
        pass

    validate_value(object(), Any, "value")
    validate_value(Child(), Parent, "value")
    assert is_type_compatible(Child, Parent)
    assert not is_type_compatible(Parent, Child)
    assert is_type_compatible(int, Any)
    assert not is_type_compatible(Any, int)
    assert is_type_compatible(int, int | str)
    assert is_type_compatible(int | str, object)
    assert not is_type_compatible(int | str, int)
    assert not is_type_compatible(list[Child], list[Parent])
    assert not is_type_compatible(list[Any], list[int])
    assert is_type_compatible(list[int], list[int])
    with pytest.raises(SchemaError, match="unresolved"):
        validate_type(TypeVar("Unknown"))


def test_registration_never_initializes_and_schema_is_a_snapshot() -> None:
    initializations: list[str] = []

    class Deferred(Node):
        amount = Property[int](default=1)

        def __init__(self) -> None:
            initializations.append("called")

    node_type(Deferred)
    Deferred.amount.default = 2
    assert initializations == []
    assert node_type_schema(Deferred).properties["amount"].default == 1


def test_python_mro_hides_inherited_declarations() -> None:
    class PortBase(Node):
        item = Input[int](default=True)

    class PlainBase(Node):
        pass

    # Exercise a runtime shadow without putting a static error in the test suite.
    setattr(PlainBase, "item", 1)  # noqa: B010

    @node_type
    class Hidden(PlainBase, PortBase):
        pass

    assert not node_type_schema(Hidden).inputs

    class Duplicate(PortBase):
        other = Input[int](default=True)

    with pytest.raises(SchemaError, match="default"):
        node_type(Duplicate)

    @node_type
    class Override(PortBase):
        item = Input[int]()
        other = Input[int](default=True)

    assert not node_type_schema(Override).inputs["item"].default
    assert node_type_schema(Override).inputs["other"].default


@pytest.mark.parametrize(
    "spec",
    [
        GenericAlias(list, (int, str)),
        GenericAlias(dict, (str,)),
        GenericAlias(tuple, (int, Ellipsis, str)),
        "Missing",
    ],
)
def test_malformed_runtime_types_fail_clearly(spec: object) -> None:
    with pytest.raises(SchemaError, match=r"unsupported|unresolved"):
        validate_type(spec)


@pytest.mark.parametrize(
    "spec",
    [
        GenericAlias(list, (Ellipsis,)),
        GenericAlias(dict, (str, Ellipsis)),
        GenericAlias(dict, (Ellipsis, str)),
        GenericAlias(set, (Ellipsis,)),
        GenericAlias(frozenset, (Ellipsis,)),
        GenericAlias(tuple, (Ellipsis, Ellipsis)),
    ],
)
def test_ellipsis_is_only_valid_as_variadic_tuple_marker(spec: object) -> None:
    with pytest.raises(SchemaError, match="unsupported"):
        validate_type(spec)


@pytest.mark.parametrize(
    "declaration", [Property[int](default=1), Input[int](), Output[int]()]
)
def test_descriptor_reuse_in_one_class_is_rejected(
    declaration: Property[int] | Input[int] | Output[int],
) -> None:
    with pytest.raises(SchemaError, match="reuse"):

        class Reused(Node):
            first = second = declaration


def test_protocol_payloads_are_rejected_clearly() -> None:
    from typing import Protocol, runtime_checkable

    @runtime_checkable
    class Data(Protocol):
        value: int

    class Invalid(Node):
        incoming = Input[Data]()

    with pytest.raises(SchemaError, match=r"incoming.*unsupported.*protocol"):
        node_type(Invalid)
    with pytest.raises(SchemaError, match=r"destination.*unsupported.*protocol"):
        is_type_compatible(object, Data)


def test_annotated_payloads_fail_with_contextual_schema_error() -> None:
    from typing import Annotated

    class Invalid(Node):
        incoming = Input[Annotated[int, "units"]]()

    with pytest.raises(SchemaError, match=r"incoming.*unsupported"):
        node_type(Invalid)
