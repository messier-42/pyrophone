"""Configured node occurrences and named graph connections."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal
from uuid import uuid4

from ._exceptions import GraphError
from ._node import Node, _resolve_configuration, node_type_schema
from ._schema import NodeTypeSchema, PortSchema, is_type_compatible

type Direction = Literal["input", "output"]


@dataclass(frozen=True, eq=False)
class NodeDeclaration:
    """An occurrence, with independent configuration and a stable unique ID.

    Configuration is shallowly read-only; nested values are copied on creation.
    No live node or user initializer is involved in creating a declaration.
    Named attributes expose ports; use ``port(name)`` for ports whose names
    collide with declaration fields or methods (such as ``id`` or ``port``).
    """

    node_type: type[Node]
    configuration: Mapping[str, object] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex, init=False)
    schema: NodeTypeSchema = field(init=False)

    def __post_init__(self) -> None:
        schema = node_type_schema(self.node_type)
        object.__setattr__(self, "schema", schema)
        object.__setattr__(
            self,
            "configuration",
            MappingProxyType(_resolve_configuration(schema, self.configuration)),
        )

    def port(self, name: str) -> "PortReference":
        if name in self.schema.inputs:
            return PortReference(self, name, "input")
        if name in self.schema.outputs:
            return PortReference(self, name, "output")
        raise AttributeError(f"{self.schema.name}: no port named {name!r}")

    def __getattr__(self, name: str) -> "PortReference":
        return self.port(name)

    def __or__(self, other: "NodeDeclaration") -> "Graph":
        return Graph(self) | other


@dataclass(frozen=True)
class PortReference:
    """A named port on one occurrence, never a live runtime endpoint."""

    node: NodeDeclaration
    name: str
    direction: Direction

    @property
    def schema(self) -> PortSchema:
        if self.direction not in ("input", "output"):
            raise GraphError(f"invalid port direction {self.direction!r}")
        ports = (
            self.node.schema.inputs
            if self.direction == "input"
            else self.node.schema.outputs
        )
        if self.name not in ports:
            raise GraphError(
                f"{self.node.schema.name}: unknown {self.direction} port {self.name!r}"
            )
        return ports[self.name]


@dataclass(frozen=True)
class Edge:
    source: PortReference
    destination: PortReference


def _validate_connection(
    source: PortReference, destination: PortReference, connected: set[PortReference]
) -> None:
    if not isinstance(source, PortReference) or not isinstance(
        destination, PortReference
    ):
        raise GraphError("connections require a named port reference at each end")
    if source.direction != "output" or destination.direction != "input":
        raise GraphError("connections must run from an output port to an input port")
    source_schema, destination_schema = source.schema, destination.schema
    if source in connected or destination in connected:
        raise GraphError("port is already connected; each port permits one channel")
    if not is_type_compatible(source_schema.type, destination_schema.type):
        raise GraphError(
            f"incompatible port types: {source.name} ({source_schema.type}) -> "
            f"{destination.name} ({destination_schema.type})"
        )


def _implicit_port(node: NodeDeclaration, direction: Direction) -> PortReference:
    ports = node.schema.inputs if direction == "input" else node.schema.outputs
    defaults = [port for port in ports.values() if port.default]
    if defaults:
        return node.port(defaults[0].name)
    if len(ports) == 1:
        return node.port(next(iter(ports)))
    if not ports:
        raise GraphError(
            f"{node.schema.name}: no {direction} port for implicit connection"
        )
    raise GraphError(
        f"{node.schema.name}: ambiguous {direction} ports; "
        "choose a named port or declare default=True"
    )


class Graph:
    """Editable graph with stable tuple inspection views.

    ``connect`` atomically adds endpoints and an edge, returning this graph.
    ``graph | declaration`` returns a new graph, connecting from the last node
    in insertion order. Implicit selection uses only declared direction/default
    metadata; existing bindings and compatible types never change that choice.
    """

    def __init__(self, *nodes: NodeDeclaration) -> None:
        self._nodes: dict[str, NodeDeclaration] = {}
        self._edges: list[Edge] = []
        for node in nodes:
            if not isinstance(node, NodeDeclaration):
                raise GraphError("graphs require node declarations")
            self._nodes[node.id] = node

    @property
    def nodes(self) -> tuple[NodeDeclaration, ...]:
        return tuple(self._nodes.values())

    @property
    def edges(self) -> tuple[Edge, ...]:
        return tuple(self._edges)

    def connect(self, source: PortReference, destination: PortReference) -> "Graph":
        connected = {
            port for edge in self._edges for port in (edge.source, edge.destination)
        }
        _validate_connection(source, destination, connected)
        # Nothing mutates until every check has succeeded, including endpoints
        # that were not already part of the graph.
        self._nodes[source.node.id] = source.node
        self._nodes[destination.node.id] = destination.node
        self._edges.append(Edge(source, destination))
        return self

    def __or__(self, other: NodeDeclaration) -> "Graph":
        if not isinstance(other, NodeDeclaration):
            raise GraphError("implicit connections require a node declaration")
        if not self._nodes:
            raise GraphError("implicit connections require a source node")
        source = _implicit_port(self.nodes[-1], "output")
        destination = _implicit_port(other, "input")
        result = Graph(*self.nodes)
        result._edges = list(self._edges)
        return result.connect(source, destination)
