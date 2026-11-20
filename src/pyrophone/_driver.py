"""Shared command-line preparation for Python scripts and a future CLI."""

import argparse
from collections.abc import Sequence

from ._graph import Graph
from ._runner import _Factory, run_sync


def drive(target: Graph | _Factory, *, argv: Sequence[str] | None = None) -> None:
    """Parse runtime arguments before building or executing a graph.

    There are no runtime options yet beyond argparse's standard help. Future
    runtime configuration belongs here, before handing control to the runner.
    ``argv=None`` reads the process arguments, as for any argparse program.
    """
    parser = argparse.ArgumentParser(description="Run a Pyrophone graph.")
    parser.parse_args(argv)
    run_sync(target)
