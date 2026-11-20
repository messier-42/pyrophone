"""Graph inspection uses the validated snapshot before allocating live nodes."""

import asyncio
import json
import shutil
import subprocess
from typing import Any

import pytest
import yaml

import pyrophone as pp
from pyrophone._driver import drive


@pytest.fixture
def example() -> tuple[pp.Graph, list[str]]:
    events: list[str] = []

    @pp.node_type
    class Source(pp.Node):
        settings = pp.Property[dict[str, Any]](
            default={
                "text": "yes: café\nnext line",
                "enabled": True,
                "data": b"\x00\xff",
            }
        )
        out_port = pp.Output[int]()

        def __init__(self) -> None:
            events.append("initialized")

        async def run(self) -> None:
            events.append("ran")
            await self.out_port.send(9)

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[int]()

        async def run(self) -> None:
            async for value in self.in_port:
                print(f"VALUE {value}")

    return pp.NodeDeclaration(Source) | pp.NodeDeclaration(Sink), events


@pytest.mark.parametrize("factory_kind", ["graph", "sync", "async"])
@pytest.mark.parametrize("show", [False, True])
def test_dump_is_yaml_and_never_initializes_nodes(
    example: tuple[pp.Graph, list[str]],
    capsys: pytest.CaptureFixture[str],
    factory_kind: str,
    show: bool,
) -> None:
    graph, events = example
    calls: list[str] = []

    def build() -> pp.Graph:
        calls.append("built")
        return graph

    async def build_async() -> pp.Graph:
        await asyncio.sleep(0)
        return build()

    argv = ["--pp-dump-graph"] + (["--pp-show-graph"] if show else [])
    target = (
        graph
        if factory_kind == "graph"
        else build
        if factory_kind == "sync"
        else build_async
    )
    drive(target, argv=argv)
    output = capsys.readouterr()
    document = yaml.safe_load(output.out)
    assert document["version"] == 1
    assert [node["id"] for node in document["nodes"]] == [
        node.id for node in graph.nodes
    ]
    assert document["nodes"][0]["type"].endswith(".Source")
    assert document["nodes"][0]["configuration"] == dict(graph.nodes[0].configuration)
    assert document["edges"] == [
        {
            "source": {"node": graph.nodes[0].id, "port": "out_port"},
            "destination": {"node": graph.nodes[1].id, "port": "in_port"},
        }
    ]
    assert ("Graph" in output.err) == show
    assert events == []
    assert calls == ([] if factory_kind == "graph" else ["built"])


def test_show_describes_connections_and_still_runs(
    example: tuple[pp.Graph, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    graph, events = example
    drive(graph, argv=["--pp-show-graph"])
    output = capsys.readouterr()
    assert "2 nodes" in output.err and "1 channels" in output.err
    assert "Source" in output.err and "Sink" in output.err
    assert "[1].out_port -> [2].in_port" in output.err
    assert output.out == "VALUE 9\n"
    assert events == ["initialized", "ran"]


def test_dump_validates_connections_before_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @pp.node_type
    class Unconnected(pp.Node):
        out_port = pp.Output[int]()

    with pytest.raises(pp.GraphError, match="unconnected"):
        drive(pp.Graph(pp.NodeDeclaration(Unconnected)), argv=["--pp-dump-graph"])
    assert capsys.readouterr().out == ""


def test_dump_rejects_unsupported_properties_without_partial_yaml(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @pp.node_type
    class Unsupported(pp.Node):
        value = pp.Property[object](default=object())

        def __init__(self) -> None:
            pytest.fail("dump must not create live nodes")

    with pytest.raises(pp.GraphError, match="YAML"):
        drive(pp.Graph(pp.NodeDeclaration(Unsupported)), argv=["--pp-dump-graph"])
    assert capsys.readouterr().out == ""


def test_dump_empty_graph(capsys: pytest.CaptureFixture[str]) -> None:
    drive(pp.Graph(), argv=["--pp-dump-graph"])
    assert yaml.safe_load(capsys.readouterr().out) == {
        "version": 1,
        "nodes": [],
        "edges": [],
    }


@pytest.mark.parametrize("execute", [False, True])
def test_graph_observer_sees_exact_snapshot_before_initialization(
    execute: bool,
) -> None:
    values: list[int] = []
    stages: list[str] = []

    @pp.node_type
    class Worker(pp.Node):
        setting = pp.Property[list[int]](default=[1])

        def __init__(self) -> None:
            stages.append("initialized")

        async def run(self) -> None:
            values.extend(self.setting)

    declaration = pp.NodeDeclaration(Worker)
    graph = pp.Graph(declaration)

    def observe(snapshot: pp.CompiledGraph) -> None:
        stages.append("observed")
        assert snapshot.nodes[0].configuration["setting"] == [1]
        # Mutating the authoring graph must not affect the snapshot being run.
        setting = declaration.configuration["setting"]
        assert isinstance(setting, list)
        setting.append(2)

    pp.run_sync(graph, on_graph=observe, execute=execute)
    assert stages == (["observed", "initialized"] if execute else ["observed"])
    assert values == ([1] if execute else [])


def test_inspection_preserves_branches_cycles_and_repeated_node_types(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @pp.node_type
    class Router(pp.Node):
        in_a = pp.Input[int]()
        in_b = pp.Input[int]()
        out_a = pp.Output[int]()
        out_b = pp.Output[int]()

    first, second = pp.NodeDeclaration(Router), pp.NodeDeclaration(Router)
    graph = pp.Graph(first, second)
    for source, destination in ((first, second), (second, first)):
        graph.connect(source.port("out_a"), destination.port("in_a"))
        graph.connect(source.port("out_b"), destination.port("in_b"))
    drive(graph, argv=["--pp-show-graph", "--pp-dump-graph"])
    output = capsys.readouterr()
    assert "[1].out_a -> [2].in_a" in output.err
    assert "[1].out_b -> [2].in_b" in output.err
    assert "[2].out_a -> [1].in_a" in output.err
    assert "[2].out_b -> [1].in_b" in output.err
    document = yaml.safe_load(output.out)
    assert len(document["nodes"]) == 2
    assert len(document["edges"]) == 4
    assert {edge["source"]["node"] for edge in document["edges"]} == {
        first.id,
        second.id,
    }


@pytest.mark.parametrize("flag", ["--pp-show-graph", "--pp-dump-graph"])
@pytest.mark.parametrize("format_name", ["pretty", "yaml", "graphviz"])
@pytest.mark.parametrize("equals", [False, True])
def test_both_flags_accept_every_format(
    example: tuple[pp.Graph, list[str]],
    capsys: pytest.CaptureFixture[str],
    flag: str,
    format_name: str,
    equals: bool,
) -> None:
    graph, events = example
    drive(graph, argv=[f"{flag}={format_name}"] if equals else [flag, format_name])
    output = capsys.readouterr()
    text = output.err if flag == "--pp-show-graph" else output.out
    if format_name == "pretty":
        assert text.startswith("Graph: 2 nodes")
    elif format_name == "yaml":
        assert len(yaml.safe_load(text)["nodes"]) == 2
    else:
        assert text.startswith("digraph pyrophone {")
        assert f'"{graph.nodes[0].id}" -> "{graph.nodes[1].id}"' in text
        assert 'label="out_port -> in_port"' in text
    assert events == (["initialized", "ran"] if flag == "--pp-show-graph" else [])
    if flag == "--pp-show-graph":
        assert output.out == "VALUE 9\n"
    else:
        assert output.err == ""


def test_combined_flags_use_independent_formats_and_skip_execution(
    example: tuple[pp.Graph, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    graph, events = example
    drive(graph, argv=["--pp-show-graph=yaml", "--pp-dump-graph=graphviz"])
    output = capsys.readouterr()
    assert len(yaml.safe_load(output.err)["nodes"]) == 2
    assert output.out.startswith("digraph pyrophone {")
    assert events == []


@pytest.mark.parametrize("flag", ["--pp-show-graph", "--pp-dump-graph"])
@pytest.mark.parametrize("format_name", ["", "unsupported"])
def test_invalid_formats_fail_before_building_graph(
    flag: str, format_name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    def build() -> pp.Graph:
        pytest.fail("invalid format must be rejected before calling the factory")

    with pytest.raises(SystemExit) as caught:
        drive(build, argv=[f"{flag}={format_name}"])
    assert caught.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_graphviz_quotes_labels_and_keeps_repeated_nodes_distinct(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @pp.node_type
    class Worker(pp.Node):
        pass

    Worker.__qualname__ = 'café "quoted" \\N\nnext line'
    first, second = pp.NodeDeclaration(Worker), pp.NodeDeclaration(Worker)
    drive(pp.Graph(first, second), argv=["--pp-dump-graph=graphviz"])
    output = capsys.readouterr().out
    assert f'"{first.id}" [label=' in output
    assert f'"{second.id}" [label=' in output
    assert 'café \\"quoted\\" \\\\N\\nnext line' in output
    assert output.endswith("}\n")


@pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz renderer is optional")
def test_graphviz_renderer_accepts_escaped_labels_cycles_and_parallel_edges(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @pp.node_type
    class Router(pp.Node):
        in_a = pp.Input[int]()
        in_b = pp.Input[int]()
        out_a = pp.Output[int]()
        out_b = pp.Output[int]()

    Router.__qualname__ = 'café "quoted" \\N\nnext line'
    first, second = pp.NodeDeclaration(Router), pp.NodeDeclaration(Router)
    graph = pp.Graph(first, second)
    for source, destination in ((first, second), (second, first)):
        graph.connect(source.port("out_a"), destination.port("in_a"))
        graph.connect(source.port("out_b"), destination.port("in_b"))
    drive(graph, argv=["--pp-dump-graph=graphviz"])
    result = subprocess.run(
        ["dot", "-Tjson"],
        input=capsys.readouterr().out,
        capture_output=True,
        text=True,
        check=True,
    )
    document = json.loads(result.stdout)
    assert {node["name"] for node in document["objects"]} == {first.id, second.id}
    assert len(document["edges"]) == 4
    assert {edge["label"] for edge in document["edges"]} == {
        "out_a -> in_a",
        "out_b -> in_b",
    }
    assert result.stderr == ""
