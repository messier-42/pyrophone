"""Errors raised while declaring, configuring, and executing nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._node import Node


class PyrophoneError(Exception):
    """Base class for errors reported by Pyrophone."""


class SchemaError(PyrophoneError, ValueError):
    """A node declaration has an invalid or unresolved schema."""


class ConfigurationError(PyrophoneError, ValueError):
    """Configuration does not satisfy a node's schema."""


class GraphError(PyrophoneError, ValueError):
    """A graph connection or compiled graph is invalid."""


class EndOfStream(PyrophoneError):
    """The input channel has closed and no more values can arrive."""


class ChannelClosedError(PyrophoneError):
    """A value could not be accepted because the channel has closed."""


class NodeExecutionError(PyrophoneError):
    """A node initializer or run method failed; __cause__ holds the original."""

    def __init__(self, node_id: str, node_type: type[Node]) -> None:
        self.node_id = node_id
        self.node_type = node_type
        self.node_type_name = node_type.__name__
        super().__init__(f"node {self.node_type_name} ({node_id}) failed")
