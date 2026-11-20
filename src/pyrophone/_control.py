"""External handles for synchronous edits to per-instance configuration."""

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from types import MappingProxyType

from ._compile import CompiledGraph, CompiledNode
from ._inspection import Printable, node_details
from ._node import Node
from ._schema import NodeTypeSchema, validate_property


class NodeHandle(Printable):
    """Runtime-owned editing access to one node, without exposing its instance.

    Attribute assignment validates and immediately replaces a property value.
    Edits must run on the node's event loop while the node is active. Reads and
    configuration snapshots are detached copies; edit containers by assignment.
    For names colliding with handle metadata/methods, use get_property/set_property.
    """

    def __init__(self, definition: CompiledNode, instance: Node) -> None:
        object.__setattr__(self, "_definition", definition)
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_active", True)
        object.__setattr__(self, "_loop", asyncio.get_running_loop())

    _definition: CompiledNode
    _instance: Node
    _active: bool
    _loop: asyncio.AbstractEventLoop

    @property
    def id(self) -> str:
        return self._definition.id

    @property
    def node_type(self) -> type[Node]:
        return self._definition.node_type

    @property
    def schema(self) -> NodeTypeSchema:
        return self._definition.schema

    @property
    def active(self) -> bool:
        return self._active

    @property
    def configuration(self) -> Mapping[str, object]:
        """Return a detached, read-only snapshot of current property values."""
        return MappingProxyType(deepcopy(dict(self._instance._configuration)))

    def __getattr__(self, name: str) -> object:
        return self.get_property(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_") or hasattr(type(self), name):
            raise AttributeError(f"{name} is read-only handle metadata")
        self.set_property(name, value)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | self.schema.properties.keys())

    def get_property(self, name: str) -> object:
        """Read a property by name, including names reserved by the handle."""
        if name not in self.schema.properties:
            raise AttributeError(f"{self.schema.name}: no property named {name!r}")
        return deepcopy(self._instance._configuration[name])

    def set_property(self, name: str, value: object) -> None:
        """Validate, copy, and apply one value without yielding or invoking hooks."""
        if name not in self.schema.properties:
            raise AttributeError(f"{self.schema.name}: no property named {name!r}")
        if not self.active:
            raise RuntimeError(f"{self.schema.name}: node has stopped")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not self._loop:
            raise RuntimeError("property changes must run on the node's event loop")
        copied = deepcopy(value)
        validate_property(copied, self.schema.properties[name])
        configuration = dict(self._instance._configuration)
        configuration[name] = copied
        object.__setattr__(
            self._instance, "_configuration", MappingProxyType(configuration)
        )

    def _close(self) -> None:
        object.__setattr__(self, "_active", False)

    def __repr__(self) -> str:
        status = "active" if self.active else "stopped"
        return f"<NodeHandle {self.node_type.__name__}#{self.id[:8]} ({status})>"

    def _describe(self) -> str:
        return node_details(
            self.node_type,
            self.configuration,
            self.schema,
            kind="NodeHandle",
            node_id=self.id,
        )


class Runtime(Printable):
    """Runtime-owned controller exposing handles in graph insertion order."""

    def __init__(
        self, compiled_graph: CompiledGraph, nodes: tuple[NodeHandle, ...]
    ) -> None:
        self._compiled_graph = compiled_graph
        self._nodes = nodes

    @property
    def nodes(self) -> tuple[NodeHandle, ...]:
        return self._nodes

    @property
    def compiled_graph(self) -> CompiledGraph:
        """The startup snapshot; live edits do not mutate it."""
        return self._compiled_graph

    def __repr__(self) -> str:
        return f"Runtime(nodes={len(self.nodes)}, active={sum(n.active for n in self.nodes)})"

    def _describe(self) -> str:
        from ._graph_display import format_graph

        current = CompiledGraph(
            tuple(
                CompiledNode(node.id, node.node_type, node.configuration, node.schema)
                for node in self.nodes
            ),
            self.compiled_graph.edges,
        )
        return format_graph(current, title="Runtime")
