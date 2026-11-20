"""Graph construction stays declarative until the runtime allocation boundary."""

from collections.abc import Callable
from typing import cast

import pytest

import pyrophone as pp
from pyrophone import (
    ConfigurationError,
    Input,
    Node,
    NodeDeclaration,
    Output,
    Property,
    SchemaError,
    node_type,
)


def declare(cls: type[Node], **configuration: object) -> "NodeDeclaration":
    # Constructor/handle checker synthesis is deferred to the future plugin.
    return cast("Callable[..., NodeDeclaration]", cls)(**configuration)


def test_construction_does_not_call_user_initializer_or_run() -> None:
    events: list[str] = []

    @node_type
    class Stateful(Node):
        def __init__(self) -> None:
            events.append("initialize")

        async def run(self) -> None:
            events.append("run")

    declaration = declare(Stateful)
    assert events == []
    assert not isinstance(declaration, Node)
    assert declaration.node_type is Stateful


def test_property_named_cls_does_not_collide_with_constructor_receiver() -> None:
    events: list[str] = []

    @node_type
    class Configured(Node):
        cls = Property[int](default=1)

        def __init__(self) -> None:
            events.append("initialize")

    declaration = cast(Callable[..., NodeDeclaration], Configured)(cls=2)
    assert declaration.configuration["cls"] == 2
    assert events == []


def test_declaration_resolves_validates_and_copies_configuration() -> None:
    @node_type
    class Configured(Node):
        required = Property[str]()
        amount = Property[int](default=3, minimum=1, maximum=5)
        values = Property[list[int]](default=[])

    supplied = [1]
    first = declare(Configured, required="first", values=supplied)
    second = declare(Configured, required="second")
    third = declare(Configured, required="third")
    assert first.id != second.id != third.id
    assert first.configuration["amount"] == 3
    supplied.append(2)
    assert first.configuration["values"] == [1]
    cast(list[int], second.configuration["values"]).append(4)
    assert third.configuration["values"] == []
    with pytest.raises(TypeError):
        first.configuration["amount"] = 4  # type: ignore[index]
    for values in (
        {},
        {"required": 1},
        {"required": "x", "amount": 0},
        {"required": "x", "amount": 6},
        {"required": "x", "typo": 1},
    ):
        with pytest.raises(ConfigurationError):
            declare(Configured, **values)


def test_concrete_subclasses_require_their_own_registration() -> None:
    @node_type
    class Parent(Node):
        value = Property[int](default=1)

    class Child(Parent):
        pass

    with pytest.raises(SchemaError, match="not a registered node type"):
        declare(Child)
    node_type(Child)
    assert declare(Child).configuration["value"] == 1


@node_type
class Source(Node):
    out_port = Output[int](description="Numbers")


@node_type
class Add(Node):
    amount = Property[int](default=1)
    in_port = Input[int]()
    out_port = Output[int]()


@node_type
class Sink(Node):
    in_port = Input[int]()


def test_pipeline_and_explicit_graph_have_the_same_named_edges() -> None:
    source, add, sink = declare(Source), declare(Add, amount=3), declare(Sink)
    pipeline = source | add | sink
    explicit = pp.Graph(source, add, sink)
    assert explicit.connect(source.out_port, add.in_port) is explicit
    explicit.connect(add.out_port, sink.in_port)
    assert pipeline.nodes == explicit.nodes == (source, add, sink)
    assert pipeline.edges == explicit.edges
    assert source.out_port.node is source
    assert source.out_port.name == "out_port"
    assert source.out_port.direction == "output"
    assert source.out_port.schema.description == "Numbers"
    assert source.out_port.schema.type is int
    assert add.in_port.direction == "input"
    compiled = pp.compile_graph(pipeline)
    assert tuple(node.id for node in compiled.nodes) == (source.id, add.id, sink.id)
    assert compiled.edges[0].source_id == source.id
    assert compiled.edges[0].source_port == "out_port"
    assert compiled.edges[0].destination_id == add.id
    assert compiled.edges[0].destination_port == "in_port"


def test_named_lookup_handles_collisions_and_unknown_ports() -> None:
    @node_type
    class Collision(Node):
        id = Output[int]()
        port = Output[str]()

    collision = declare(Collision)
    sink = declare(Sink)
    assert isinstance(collision.id, str)
    assert collision.port("id").schema.type is int
    assert collision.port("port").schema.type is str
    assert pp.Graph().connect(collision.port("id"), sink.in_port).nodes == (
        collision,
        sink,
    )
    with pytest.raises(AttributeError, match="missing"):
        collision.port("missing")
    with pytest.raises(AttributeError, match="missing"):
        _ = collision.missing
    with pytest.raises(pp.GraphError, match="port reference"):
        pp.Graph().connect(cast("pp.PortReference", collision.id), sink.in_port)


def test_implicit_selection_uses_default_metadata_and_does_not_guess() -> None:

    @node_type
    class Multi(Node):
        primary = Input[int](default=True)
        secondary = Input[int]()
        result = Output[int](default=True)
        other = Output[int]()

    source, multi, sink = declare(Source), declare(Multi), declare(Sink)
    graph = source | multi | sink
    assert graph.edges[0].destination.name == "primary"
    assert graph.edges[1].source.name == "result"


def test_ambiguous_ports_require_explicit_connections_even_if_one_is_compatible() -> (
    None
):
    @node_type
    class Multi(Node):
        numbers = Output[int]()
        text = Output[str]()

    multi = declare(Multi)
    with pytest.raises(pp.GraphError, match=r"ambiguous.*output"):
        _ = multi | declare(Sink)
    with pytest.raises(pp.GraphError, match=r"no.*output"):
        _ = declare(Sink) | declare(Sink)
    with pytest.raises(pp.GraphError, match=r"no.*input"):
        _ = declare(Source) | declare(Source)


def test_implicit_selection_does_not_fall_back_when_default_is_bound() -> None:
    @node_type
    class Split(Node):
        primary = Output[int](default=True)
        secondary = Output[int]()

    split, sink = declare(Split), declare(Sink)
    # End the explicit node order at split so graph | sink pipes from split.
    graph = pp.Graph(sink, split).connect(split.primary, sink.in_port)
    with pytest.raises(pp.GraphError, match="already connected"):
        _ = graph | declare(Sink)


def test_explicit_branches_reuse_occurrence_with_distinct_ports() -> None:
    @node_type
    class Split(Node):
        first = Output[int]()
        second = Output[int]()

    split, left, right = declare(Split), declare(Sink), declare(Sink)
    graph = pp.Graph(split, split)
    graph.connect(split.first, left.in_port).connect(split.second, right.in_port)
    assert graph.nodes == (split, left, right)
    assert len(pp.compile_graph(graph).edges) == 2


def test_failed_connections_are_atomic_for_directions_types_and_repeated_ports() -> (
    None
):
    @node_type
    class TextSink(Node):
        in_port = Input[str]()

    source, sink = declare(Source), declare(Sink)
    text_sink, other_source, other_sink = (
        declare(TextSink),
        declare(Source),
        declare(Sink),
    )
    graph = pp.Graph()
    for output, input_ in (
        (sink.in_port, source.out_port),
        (source.out_port, text_sink.in_port),
    ):
        with pytest.raises(pp.GraphError):
            graph.connect(output, input_)
        assert graph.nodes == ()
        assert graph.edges == ()
    graph.connect(source.out_port, sink.in_port)
    old_nodes, old_edges = graph.nodes, graph.edges
    for output, input_ in (
        (source.out_port, sink.in_port),
        (source.out_port, other_sink.in_port),
        (other_source.out_port, sink.in_port),
    ):
        with pytest.raises(pp.GraphError, match="already connected"):
            graph.connect(output, input_)
        assert graph.nodes == old_nodes
        assert graph.edges == old_edges


def test_compile_requires_every_port_but_accepts_portless_nodes() -> None:
    source, add, sink = declare(Source), declare(Add), declare(Sink)
    with pytest.raises(pp.GraphError, match=r"unconnected.*in_port"):
        pp.compile_graph(pp.Graph(add))
    with pytest.raises(pp.GraphError, match=r"unconnected.*out_port"):
        pp.compile_graph(
            pp.Graph(source, add, sink).connect(source.out_port, add.in_port)
        )

    @node_type
    class Portless(Node):
        pass

    empty = pp.compile_graph(pp.Graph())
    portless = declare(Portless)
    assert empty.nodes == ()
    assert empty.edges == ()
    assert pp.compile_graph(pp.Graph(portless)).nodes[0].id == portless.id


def test_compilation_and_inspection_views_are_detached_from_later_edits() -> None:
    @node_type
    class Configured(Node):
        values = Property[list[int]](default=[1])

    declaration = declare(Configured)
    graph = pp.Graph(declaration)
    nodes, edges = graph.nodes, graph.edges
    compiled = pp.compile_graph(graph)
    source, sink = declare(Source), declare(Sink)
    graph.connect(source.out_port, sink.in_port)
    cast(list[int], declaration.configuration["values"]).append(2)
    assert nodes == (declaration,)
    assert edges == ()
    assert len(compiled.nodes) == 1
    assert compiled.nodes[0].configuration["values"] == [1]
    assert compiled.edges == ()
    assert compiled.nodes[0].node_type is Configured
    with pytest.raises(TypeError):
        compiled.nodes[0].configuration["values"] = []  # type: ignore[index]
    cast(list[object], declaration.configuration["values"]).append("bad")
    with pytest.raises(ConfigurationError, match="values"):
        pp.compile_graph(graph)


def test_pipe_does_not_mutate_existing_graph() -> None:
    source, add, sink = declare(Source), declare(Add), declare(Sink)
    partial = source | add
    complete = partial | sink
    assert partial.nodes == (source, add)
    assert len(partial.edges) == 1
    assert complete.nodes == (source, add, sink)
    assert len(pp.compile_graph(complete).edges) == 2


@pytest.mark.parametrize(
    "invalid", ["duplicate", "reverse", "type", "missing", "outside"]
)
def test_compiler_revalidates_edges(invalid: str) -> None:
    @node_type
    class TextSink(Node):
        in_port = Input[str]()

    source, sink, text_sink = declare(Source), declare(Sink), declare(TextSink)
    graph = source | sink
    if invalid == "duplicate":
        graph._edges.append(graph.edges[0])
        message = "already connected"
    elif invalid == "reverse":
        graph._edges[0] = pp.Edge(sink.in_port, source.out_port)
        message = "output port to an input port"
    elif invalid == "type":
        graph = pp.Graph(source, text_sink)
        graph._edges.append(pp.Edge(source.out_port, text_sink.in_port))
        message = "incompatible port types"
    elif invalid == "missing":
        graph._edges[0] = pp.Edge(
            pp.PortReference(source, "typo", "output"), sink.in_port
        )
        message = "unknown output port"
    else:
        graph = pp.Graph(source)
        graph._edges.append(pp.Edge(source.out_port, sink.in_port))
        message = "outside the graph"
    with pytest.raises(pp.GraphError, match=message):
        pp.compile_graph(graph)


def test_compilation_preserves_subtyping_and_invariant_container_rules() -> None:
    @node_type
    class GeneralSink(Node):
        in_port = Input[object]()

    assert len(pp.compile_graph(declare(Source) | declare(GeneralSink)).edges) == 1

    @node_type
    class ListSource(Node):
        out_port = Output[list[int]]()

    @node_type
    class ListSink(Node):
        in_port = Input[list[object]]()

    with pytest.raises(pp.GraphError, match="incompatible port types"):
        _ = declare(ListSource) | declare(ListSink)


def test_print_text_inference_is_order_independent_and_graph_local() -> None:
    from pyrophone.nodes import PrintText

    @node_type
    class TextSource(Node):
        out_port = Output[str]()

    @node_type
    class ByteSource(Node):
        out_port = Output[bytes]()

    @node_type
    class TextSink(Node):
        in_port = Input[str]()

    @node_type
    class ByteSink(Node):
        in_port = Input[bytes]()

    printer = declare(PrintText)
    text_source, text_sink = declare(TextSource), declare(TextSink)
    byte_source, byte_sink = declare(ByteSource), declare(ByteSink)
    graph = pp.Graph().connect(printer.out_port, byte_sink.in_port)
    before = graph.nodes, graph.edges
    with pytest.raises(pp.GraphError, match="incompatible port types"):
        graph.connect(text_source.out_port, printer.in_port)
    assert (graph.nodes, graph.edges) == before
    graph.connect(byte_source.out_port, printer.in_port)
    byte_compiled = pp.compile_graph(graph)
    text_compiled = pp.compile_graph(text_source | printer | text_sink)
    assert (
        next(n for n in byte_compiled.nodes if n.id == printer.id)
        .schema.outputs["out_port"]
        .type
        is bytes
    )
    assert (
        next(n for n in text_compiled.nodes if n.id == printer.id)
        .schema.outputs["out_port"]
        .type
        is str
    )
    assert printer.schema.outputs["out_port"].type == str | bytes
    with pytest.raises(pp.GraphError, match="incompatible port types"):
        _ = declare(Source) | declare(PrintText)
    with pytest.raises(pp.GraphError, match="incompatible port types"):
        _ = declare(PrintText) | declare(Sink)
    # Compilation must resolve against the complete edge set too, even if
    # the upstream connection was added after the downstream one.
    graph._edges[1] = pp.Edge(text_source.out_port, printer.in_port)
    with pytest.raises(pp.GraphError, match="incompatible port types"):
        pp.compile_graph(graph)


def test_print_text_does_not_narrow_mixed_streams_or_unbound_cycles() -> None:
    from pyrophone.nodes import PrintText

    @node_type
    class MixedSource(Node):
        out_port = Output[str | bytes]()

    @node_type
    class ByteSink(Node):
        in_port = Input[bytes]()

    with pytest.raises(pp.GraphError, match="incompatible port types"):
        _ = declare(MixedSource) | declare(PrintText) | declare(ByteSink)
    first, second = declare(PrintText), declare(PrintText)
    cycle = pp.Graph().connect(first.out_port, second.in_port)
    cycle.connect(second.out_port, first.in_port)
    assert (
        pp.compile_graph(cycle).nodes[0].schema.outputs["out_port"].type == str | bytes
    )
