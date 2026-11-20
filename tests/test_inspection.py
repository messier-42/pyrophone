"""Readable inspection without compiling or running authoring graphs."""

import io

import pytest

import pyrophone as pp
from pyrophone._node import _bind_node


@pp.node_type
class Relay(pp.Node):
    amount = pp.Property[int](default=1)
    incoming = pp.Input[int]()
    outgoing = pp.Output[int]()


def test_reprs_are_compact_and_distinguish_occurrences() -> None:
    first, second = pp.NodeDeclaration(Relay), pp.NodeDeclaration(Relay)
    graph = first | second
    graph.connect(second.outgoing, first.incoming)
    compiled = pp.compile_graph(graph)
    objects = (
        first,
        first.incoming,
        graph.edges[0],
        graph,
        compiled.nodes[0],
        compiled.edges[0],
        compiled,
    )
    for obj in objects:
        text = repr(obj)
        assert len(text) < 150
        assert "\n" not in text
        assert "schema=" not in text
        assert "mappingproxy" not in text
        assert " at 0x" not in text
    assert repr(first) != repr(second)
    assert first.id[:8] in repr(first)
    assert "Relay" in repr(first)
    assert "outgoing" in repr(graph.edges[0])
    assert "incoming" in repr(compiled.edges[0])
    assert repr(graph) == "Graph(nodes=2, edges=2)"
    assert repr(compiled) == "CompiledGraph(nodes=2, edges=2)"


def test_print_incomplete_graph_and_node(capsys: pytest.CaptureFixture[str]) -> None:
    node = pp.NodeDeclaration(Relay, {"amount": 7})
    node.print()
    text = capsys.readouterr().out
    assert node.id in text
    assert "amount: 7" in text
    assert "incoming: int" in text
    assert "outgoing: int" in text
    graph = pp.Graph(node)
    graph.print()
    text = capsys.readouterr().out
    assert "Relay" in text and "amount: 7" in text
    assert "incoming: int" in text
    assert text.endswith("\n")


def test_print_edges_ports_and_compiled_snapshot() -> None:
    node = pp.NodeDeclaration(Relay)
    graph = pp.Graph(node).connect(node.outgoing, node.incoming)
    compiled = pp.compile_graph(graph)
    for obj in (node.outgoing, graph.edges[0], compiled.edges[0]):
        stream = io.StringIO()
        assert obj.print(file=stream) is None
        assert len(stream.getvalue().splitlines()) >= 2
        assert node.id in stream.getvalue()
    for snapshot in (compiled.nodes[0], compiled):
        stream = io.StringIO()
        snapshot.print(file=stream)
        assert "amount: 1" in stream.getvalue()
        assert "incoming: int" in stream.getvalue()
    stream = io.StringIO()
    compiled.print(file=stream)
    assert "[1].outgoing -> [1].incoming" in stream.getvalue()


def test_live_node_inspection() -> None:
    node = _bind_node(
        Relay, {"amount": 3}, {"incoming": object()}, {"outgoing": object()}
    )
    assert repr(node) == "<Relay>"
    stream = io.StringIO()
    node.print(file=stream)
    assert "amount: 3" in stream.getvalue()
    assert "incoming: int" in stream.getvalue()


def test_empty_graph_print(capsys: pytest.CaptureFixture[str]) -> None:
    pp.Graph().print()
    pp.compile_graph(pp.Graph()).print()
    assert capsys.readouterr().out == (
        "Graph: 0 nodes, 0 channels\nCompiledGraph: 0 nodes, 0 channels\n"
    )


def test_print_port_remains_accessible_by_name() -> None:
    @pp.node_type
    class NamedPort(pp.Node):
        # A deliberately colliding port name still supports dynamic inspection.
        print = pp.Input[int]()  # type: ignore[assignment]

    declaration = pp.NodeDeclaration(NamedPort)
    assert declaration.port("print").name == "print"
    stream = io.StringIO()
    declaration.print(file=stream)
    assert "print: int" in stream.getvalue()
