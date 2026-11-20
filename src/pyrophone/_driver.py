"""Shared command-line preparation for Python scripts and a future CLI."""

import argparse
import sys
from collections.abc import Sequence

from ._compile import CompiledGraph
from ._graph import Graph
from ._graph_display import GRAPH_FORMATS, render_graph
from ._runner import _Factory, run_sync


def drive(target: Graph | _Factory, *, argv: Sequence[str] | None = None) -> None:
    """Parse runtime arguments before building or executing a graph.

    ``argv=None`` reads the process arguments, as for any argparse program.
    Graph inspection occurs after factory resolution and validation, before
    live nodes are created, using the exact snapshot execution will use.
    """
    parser = argparse.ArgumentParser(
        description="Run a Pyrophone graph.",
        epilog="Graph formats: " + ", ".join(GRAPH_FORMATS) + ".",
    )
    parser.add_argument(
        "--pp-show-graph",
        nargs="?",
        const="pretty",
        choices=GRAPH_FORMATS,
        metavar="FORMAT",
        help="show the final graph on stderr before execution (default: pretty)",
    )
    parser.add_argument(
        "--pp-dump-graph",
        nargs="?",
        const="yaml",
        choices=GRAPH_FORMATS,
        metavar="FORMAT",
        help="dump the final graph to stdout and exit without execution (default: yaml)",
    )
    parser.add_argument(
        "--pp-shell",
        action="store_true",
        help="open an async Python REPL on stdio alongside the graph",
    )
    options = parser.parse_args(argv)
    if (
        options.pp_show_graph is None
        and options.pp_dump_graph is None
        and not options.pp_shell
    ):
        run_sync(target)
        return

    def inspect_graph(graph: CompiledGraph) -> None:
        if options.pp_show_graph is not None:
            print(
                render_graph(graph, options.pp_show_graph),
                file=sys.stderr,
                end="",
                flush=True,
            )
        if options.pp_dump_graph is not None:
            print(render_graph(graph, options.pp_dump_graph), end="", flush=True)

    session = None
    if options.pp_shell and options.pp_dump_graph is None:
        from ._shell import run_shell

        session = run_shell
    run_sync(
        target,
        on_graph=inspect_graph,
        execute=options.pp_dump_graph is None,
        session=session,
    )
