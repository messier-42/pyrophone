"""Configured node occurrences and named graph connections."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal, get_args
from uuid import uuid4

from ._exceptions import GraphError
from ._inspection import Printable, node_details, type_name
from ._node import Node, _resolve_configuration, node_type_schema
from ._schema import NodeTypeSchema, PortSchema, is_type_compatible

type Direction = Literal["input", "output"]


@dataclass(frozen=True, eq=False)
class NodeDeclaration(Printable):
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

    def __repr__(self) -> str:
        return f"<Node {self.node_type.__name__}#{self.id[:8]}>"

    def _describe(self) -> str:
        return node_details(
            self.node_type, self.configuration, self.schema, node_id=self.id
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
class PortReference(Printable):
    """A named port on one occurrence, never a live runtime endpoint."""

    node: NodeDeclaration
    name: str
    direction: Direction

    def __repr__(self) -> str:
        return (
            f"<Port {self.node.node_type.__name__}#{self.node.id[:8]}"
            f".{self.name} ({self.direction})>"
        )

    def _describe(self) -> str:
        return (
            f"Port: {self.node.node_type.__name__}.{self.name}\n"
            f"  Node ID: {self.node.id}\n"
            f"  Direction: {self.direction}\n"
            f"  Type: {type_name(self.schema.type)}"
        )

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
class Edge(Printable):
    source: PortReference
    destination: PortReference

    def __repr__(self) -> str:
        source, destination = self.source, self.destination
        return (
            f"<Edge {source.node.node_type.__name__}#{source.node.id[:8]}"
            f".{source.name} -> "
            f"{destination.node.node_type.__name__}#{destination.node.id[:8]}"
            f".{destination.name}>"
        )

    def _describe(self) -> str:
        source, destination = self.source, self.destination
        return (
            "Edge:\n"
            f"  From: {source.node.node_type.__name__}#{source.node.id}.{source.name}"
            f" ({type_name(source.schema.type)})\n"
            f"  To: {destination.node.node_type.__name__}#{destination.node.id}"
            f".{destination.name} ({type_name(destination.schema.type)})"
        )


def _output_type(
    source: PortReference, incoming: Mapping[PortReference, PortReference]
) -> object | None:
    """Follow exact-value forwarding contracts without mutating declarations.

    An open input or a cycle without a concrete producer cannot yet infer a type.
    """
    seen: set[PortReference] = set()
    while source not in seen:
        seen.add(source)
        input_name = source.node.node_type._output_type_sources.get(source.name)
        if input_name is None:
            return source.schema.type
        upstream = incoming.get(source.node.port(input_name))
        if upstream is None:
            return None
        source = upstream
    return None


def _resolved_schema(
    node: NodeDeclaration, incoming: Mapping[PortReference, PortReference]
) -> NodeTypeSchema:
    """Specialize compiled output metadata for this graph only."""
    outputs = dict(node.schema.outputs)
    for name in node.node_type._output_type_sources:
        inferred = _output_type(node.port(name), incoming)
        if inferred is not None:
            outputs[name] = replace(outputs[name], type=inferred)
    return (
        node.schema
        if outputs == node.schema.outputs
        else replace(node.schema, outputs=outputs)
    )


def _validate_connection(
    source: PortReference,
    destination: PortReference,
    connected: set[PortReference],
    *,
    incoming: Mapping[PortReference, PortReference],
    allow_unbound: bool = False,
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
    source_type = _output_type(source, incoming)
    if source_type is None:
        source_type = source_schema.type
        # During editing a forwarder's input may be connected later. Only
        # defer if at least one allowed input type could satisfy this edge.
        if allow_unbound and any(
            is_type_compatible(part, destination_schema.type)
            for part in (get_args(source_type) or (source_type,))
        ):
            return
    if not is_type_compatible(source_type, destination_schema.type):
        raise GraphError(
            f"incompatible port types: {source.name} ({source_type}) -> "
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


class Graph(Printable):
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

    def __repr__(self) -> str:
        return f"Graph(nodes={len(self._nodes)}, edges={len(self._edges)})"

    def _describe(self) -> str:
        from ._graph_display import format_graph

        return format_graph(self)

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
        incoming = {edge.destination: edge.source for edge in self._edges}
        # Do structural validation before using caller-supplied endpoints as
        # keys. Inference of the new edge uses all existing upstream links.
        _validate_connection(
            source, destination, connected, incoming=incoming, allow_unbound=True
        )
        incoming[destination] = source
        # Binding an input can narrow downstream forwarders, including ones
        # connected earlier. Recheck those edges before mutating the graph.
        for edge in (*self._edges, Edge(source, destination)):
            _validate_connection(
                edge.source,
                edge.destination,
                set(),
                incoming=incoming,
                allow_unbound=True,
            )
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
