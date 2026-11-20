"""Validate fundamental graphs and detach execution snapshots."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ._exceptions import GraphError
from ._graph import Graph, PortReference, _resolved_schema, _validate_connection
from ._inspection import Printable, node_details
from ._node import Node, _resolve_configuration
from ._schema import NodeTypeSchema


@dataclass(frozen=True)
class CompiledNode(Printable):
    """Configured occurrence retaining its original declaration ID.

    Configuration is shallowly read-only, with nested values detached from the
    authoring declaration so subsequent graph edits cannot change execution.
    """

    id: str
    node_type: type[Node]
    configuration: Mapping[str, object]
    schema: NodeTypeSchema

    def __repr__(self) -> str:
        return f"<CompiledNode {self.node_type.__name__}#{self.id[:8]}>"

    def _describe(self) -> str:
        return node_details(
            self.node_type,
            self.configuration,
            self.schema,
            kind="CompiledNode",
            node_id=self.id,
        )


@dataclass(frozen=True)
class CompiledEdge(Printable):
    source_id: str
    source_port: str
    destination_id: str
    destination_port: str

    def __repr__(self) -> str:
        return (
            f"<CompiledEdge {self.source_id[:8]}.{self.source_port} -> "
            f"{self.destination_id[:8]}.{self.destination_port}>"
        )

    def _describe(self) -> str:
        return (
            "CompiledEdge:\n"
            f"  From: {self.source_id}.{self.source_port}\n"
            f"  To: {self.destination_id}.{self.destination_port}"
        )


@dataclass(frozen=True)
class CompiledGraph(Printable):
    nodes: tuple[CompiledNode, ...]
    edges: tuple[CompiledEdge, ...]

    def __repr__(self) -> str:
        return f"CompiledGraph(nodes={len(self.nodes)}, edges={len(self.edges)})"

    def _describe(self) -> str:
        from ._graph_display import format_graph

        return format_graph(self, title="CompiledGraph")


def compile_graph(graph: Graph) -> CompiledGraph:
    """Validate every connection and configuration without allocating live nodes.

    Every declared input and output must have exactly one channel. Empty graphs
    and portless nodes are valid. The returned tuples and copied configuration
    are independent of later authoring graph changes.
    """
    nodes, edges = graph.nodes, graph.edges
    members = set(nodes)
    connected: set[PortReference] = set()
    incoming = {edge.destination: edge.source for edge in edges}
    for edge in edges:
        _validate_connection(
            edge.source, edge.destination, connected, incoming=incoming
        )
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
                _resolved_schema(node, incoming),
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
