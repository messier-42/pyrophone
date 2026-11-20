"""Pretty, YAML, and Graphviz views of validated execution snapshots."""

import json
from collections.abc import Callable

import yaml
from yaml.representer import RepresenterError

from ._compile import CompiledGraph, CompiledNode
from ._exceptions import GraphError
from ._graph import Edge, Graph, NodeDeclaration
from ._inspection import node_details


def format_graph(graph: Graph | CompiledGraph, *, title: str = "Graph") -> str:
    """Describe nodes and named connections without requiring compilation."""
    nodes: tuple[NodeDeclaration | CompiledNode, ...] = graph.nodes
    labels = {node.id: f"[{index}]" for index, node in enumerate(nodes, 1)}
    lines = [f"{title}: {len(graph.nodes)} nodes, {len(graph.edges)} channels"]
    for node in nodes:
        details = node_details(node.node_type, node.configuration, node.schema)
        heading, *body = details.splitlines()
        lines.append(f"  {labels[node.id]} {heading.removeprefix('Node: ')}")
        lines.extend(f"  {line}" for line in body)
    if graph.edges:
        lines.append("Connections:")
        for edge in graph.edges:
            if isinstance(edge, Edge):
                source_id, source_port = edge.source.node.id, edge.source.name
                destination_id = edge.destination.node.id
                destination_port = edge.destination.name
            else:
                source_id, source_port = edge.source_id, edge.source_port
                destination_id, destination_port = (
                    edge.destination_id,
                    edge.destination_port,
                )
            lines.append(
                f"  {labels[source_id]}.{source_port} -> "
                f"{labels[destination_id]}.{destination_port}"
            )
    return "\n".join(lines)


def dump_graph(graph: CompiledGraph) -> str:
    """Export identifiers, node types, resolved configuration, and port edges.

    Configuration uses standard YAML representations, including binary data.
    Unsupported Python objects fail rather than being converted to strings.
    This exports a snapshot; it does not define a graph-loading API.
    """
    document = {
        "version": 1,
        "nodes": [
            {
                "id": node.id,
                "type": f"{node.node_type.__module__}.{node.node_type.__qualname__}",
                "configuration": dict(node.configuration),
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": {"node": edge.source_id, "port": edge.source_port},
                "destination": {
                    "node": edge.destination_id,
                    "port": edge.destination_port,
                },
            }
            for edge in graph.edges
        ],
    }
    try:
        return yaml.safe_dump(
            document, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
    except RepresenterError as error:
        raise GraphError(
            "Graph configuration contains a value unsupported by YAML"
        ) from error


def graphviz_graph(graph: CompiledGraph) -> str:
    """Export topology as DOT, retaining node identities and named connections.

    Plain quoted labels avoid Graphviz HTML/record interpretation; escaping
    protects quotes, backslashes, and newlines in user-defined type names.
    Graphviz itself is needed only to render the exported text.
    """

    def quote(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = ["digraph pyrophone {", "  rankdir=LR;", "  node [shape=box];"]
    for node in graph.nodes:
        label = f"{node.node_type.__module__}.{node.node_type.__qualname__}"
        lines.append(f"  {quote(node.id)} [label={quote(label)}];")
    for edge in graph.edges:
        label = f"{edge.source_port} -> {edge.destination_port}"
        lines.append(
            f"  {quote(edge.source_id)} -> {quote(edge.destination_id)} "
            f"[label={quote(label)}];"
        )
    lines.append("}")
    return "\n".join(lines)


GRAPH_FORMATS: dict[str, Callable[[CompiledGraph], str]] = {
    "pretty": format_graph,
    "yaml": dump_graph,
    "graphviz": graphviz_graph,
}


def render_graph(graph: CompiledGraph, format_name: str) -> str:
    """Render any supported format with exactly one trailing newline."""
    return GRAPH_FORMATS[format_name](graph).rstrip("\n") + "\n"
