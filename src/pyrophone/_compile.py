"""Validate fundamental graphs and detach execution snapshots."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ._exceptions import GraphError
from ._graph import Graph, PortReference, _validate_connection
from ._node import Node, _resolve_configuration
from ._schema import NodeTypeSchema


@dataclass(frozen=True)
class CompiledNode:
    """Configured occurrence retaining its original declaration ID.

    Configuration is shallowly read-only, with nested values detached from the
    authoring declaration so subsequent graph edits cannot change execution.
    """

    id: str
    node_type: type[Node]
    configuration: Mapping[str, object]
    schema: NodeTypeSchema


@dataclass(frozen=True)
class CompiledEdge:
    source_id: str
    source_port: str
    destination_id: str
    destination_port: str


@dataclass(frozen=True)
class CompiledGraph:
    nodes: tuple[CompiledNode, ...]
    edges: tuple[CompiledEdge, ...]


def compile_graph(graph: Graph) -> CompiledGraph:
    """Validate every connection and configuration without allocating live nodes.

    Every declared input and output must have exactly one channel. Empty graphs
    and portless nodes are valid. The returned tuples and copied configuration
    are independent of later authoring graph changes.
    """
    nodes, edges = graph.nodes, graph.edges
    members = set(nodes)
    connected: set[PortReference] = set()
    for edge in edges:
        _validate_connection(edge.source, edge.destination, connected)
        if edge.source.node not in members or edge.destination.node not in members:
            raise GraphError("connection references a node outside the graph")
        connected.update((edge.source, edge.destination))
    for node in nodes:
        for name in (*node.schema.inputs, *node.schema.outputs):
            if node.port(name) not in connected:
                raise GraphError(f"{node.schema.name}: unconnected port {name!r}")
    return CompiledGraph(
        tuple(
            CompiledNode(
                node.id,
                node.node_type,
                MappingProxyType(
                    _resolve_configuration(node.schema, node.configuration)
                ),
                node.schema,
            )
            for node in nodes
        ),
        tuple(
            CompiledEdge(
                edge.source.node.id,
                edge.source.name,
                edge.destination.node.id,
                edge.destination.name,
            )
            for edge in edges
        ),
    )
