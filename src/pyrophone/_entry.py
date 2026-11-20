"""Import-safe script decorators and direct driver entry points."""

from typing import Protocol, overload

from ._driver import drive
from ._graph import Graph
from ._runner import _Factory


def _decorate[F: _Factory](factory: F, /) -> F:
    if factory.__module__ == "__main__":
        drive(factory)
    return factory


class _Decorator(Protocol):
    def __call__[F: _Factory](self, factory: F, /) -> F: ...


@overload
def main(target: Graph, /) -> None: ...


@overload
def main[F: _Factory](target: F, /) -> F: ...


@overload
def main() -> _Decorator: ...


def main(target: Graph | _Factory | None = None, /) -> _Factory | _Decorator | None:
    """Run a graph directly, or mark a graph factory as a script entry point.

    ``main(graph)`` immediately invokes the command-line driver, even on import.
    The driver parses arguments before executing the graph or its factory.
    ``@main`` and ``@main()`` execute a zero-argument sync or async factory only
    when its module is __main__. The factory and graph share an event loop.
    Decoration always returns the original function; imported factories remain
    callable and retain their static types.

    Put decorated entry points after their dependencies: execution begins when
    Python evaluates the decorator. Empty parentheses reserve space for future
    options; no configuration arguments are currently accepted.
    """
    if target is None:
        return _decorate
    if isinstance(target, Graph):
        drive(target)
        return None
    if callable(target):
        return _decorate(target)
    raise TypeError("pyrophone.main expects a Graph or a graph factory")
