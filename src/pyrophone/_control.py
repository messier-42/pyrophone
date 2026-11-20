"""External handles for synchronous edits to per-instance configuration."""

import asyncio
from collections.abc import Callable, Mapping
from copy import deepcopy
from types import MappingProxyType
from typing import Literal, cast

from ._channels import ReceiveEndpoint, SendEndpoint
from ._compile import CompiledGraph, CompiledNode
from ._inspection import Printable, node_details, type_name
from ._node import Node
from ._schema import NodeTypeSchema, PortSchema, validate_property
from ._trace import Trace, _TraceCallbacks


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
        ports = {}
        for direction, endpoints in (
            ("input", instance._inputs),
            ("output", instance._outputs),
        ):
            for name, endpoint in endpoints.items():
                port = cast(ReceiveEndpoint[object] | SendEndpoint[object], endpoint)
                ports[name] = PortHandle(
                    self,
                    name,
                    cast(Literal["input", "output"], direction),
                    port._traces,
                )
        object.__setattr__(self, "_ports", ports)

    _definition: CompiledNode
    _instance: Node
    _active: bool
    _loop: asyncio.AbstractEventLoop
    _ports: dict[str, "PortHandle"]

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
        if name in self._ports:
            return self.port(name)
        return self.get_property(name)

    def port(self, name: str) -> "PortHandle":
        """Inspect or trace a named runtime port, including reserved names."""
        if name not in self._ports:
            raise AttributeError(f"{self.schema.name}: no port named {name!r}")
        return self._ports[name]

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_") or hasattr(type(self), name):
            raise AttributeError(f"{name} is read-only handle metadata")
        self.set_property(name, value)

    def __dir__(self) -> list[str]:
        return sorted(
            set(super().__dir__()) | self.schema.properties.keys() | self._ports.keys()
        )

    def get_property(self, name: str) -> object:
        """Read a property by name, including names reserved by the handle."""
        if name not in self.schema.properties:
            raise AttributeError(f"{self.schema.name}: no property named {name!r}")
        return deepcopy(self._instance._configuration[name])

    def set_property(self, name: str, value: object) -> None:
        """Validate, copy, and apply one value without yielding or invoking hooks."""
        if name not in self.schema.properties:
            raise AttributeError(f"{self.schema.name}: no property named {name!r}")
        self._check_active()
        copied = deepcopy(value)
        validate_property(copied, self.schema.properties[name])
        configuration = dict(self._instance._configuration)
        configuration[name] = copied
        object.__setattr__(
            self._instance, "_configuration", MappingProxyType(configuration)
        )

    def _check_active(self) -> None:
        if not self.active:
            raise RuntimeError(f"{self.schema.name}: node has stopped")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not self._loop:
            raise RuntimeError("runtime changes must run on the node's event loop")

    def _close(self) -> None:
        object.__setattr__(self, "_active", False)
        for port in self._ports.values():
            port._traces.close()

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


class PortHandle(Printable):
    """Inspection and tracing access to one live port; it cannot send or receive."""

    def __init__(
        self,
        node: NodeHandle,
        name: str,
        direction: Literal["input", "output"],
        traces: _TraceCallbacks[object],
    ) -> None:
        self._node, self._name, self._direction, self._traces = (
            node,
            name,
            direction,
            traces,
        )

    @property
    def node(self) -> NodeHandle:
        return self._node

    @property
    def name(self) -> str:
        return self._name

    @property
    def direction(self) -> Literal["input", "output"]:
        return self._direction

    @property
    def schema(self) -> PortSchema:
        ports = (
            self.node.schema.inputs
            if self.direction == "input"
            else self.node.schema.outputs
        )
        return ports[self.name]

    def trace(self, callback: Callable[[object], None]) -> Trace:
        """Observe accepted transfers synchronously. The callback must not block."""
        self.node._check_active()
        return self._traces.add(callback)

    def __repr__(self) -> str:
        return f"<PortHandle {self.node.node_type.__name__}#{self.node.id[:8]}.{self.name} ({self.direction})>"

    def _describe(self) -> str:
        return (
            f"Port: {self.node.node_type.__name__}.{self.name}\n"
            f"  Node ID: {self.node.id}\n"
            f"  Direction: {self.direction}\n"
            f"  Type: {type_name(self.schema.type)}\n"
            f"  Traces: {len(self._traces.snapshot())}"
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
