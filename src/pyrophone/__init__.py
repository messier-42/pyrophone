"""Typed declarations for asynchronous message-processing nodes."""

from ._compile import CompiledEdge, CompiledGraph, CompiledNode, compile_graph
from ._control import NodeHandle, PortHandle, Runtime
from ._entry import main
from ._exceptions import (
    ChannelClosedError,
    ConfigurationError,
    EndOfStream,
    GraphError,
    NodeExecutionError,
    PyrophoneError,
    SchemaError,
)
from ._graph import Edge, Graph, NodeDeclaration, PortReference
from ._node import Node, node_type, node_type_schema
from ._ports import Input, InputPort, Output, OutputPort
from ._properties import Property
from ._runner import run_sync
from ._runtime import run_async
from ._schema import NodeTypeSchema, PortSchema, PropertySchema
from ._trace import Trace

# Compatibility with the original asynchronous entry point.
run = run_async

__all__ = [
    "ChannelClosedError",
    "CompiledEdge",
    "CompiledGraph",
    "CompiledNode",
    "ConfigurationError",
    "Edge",
    "EndOfStream",
    "Graph",
    "GraphError",
    "Input",
    "InputPort",
    "Node",
    "NodeDeclaration",
    "NodeExecutionError",
    "NodeHandle",
    "NodeTypeSchema",
    "Output",
    "OutputPort",
    "PortHandle",
    "PortReference",
    "PortSchema",
    "Property",
    "PropertySchema",
    "PyrophoneError",
    "Runtime",
    "SchemaError",
    "Trace",
    "compile_graph",
    "main",
    "node_type",
    "node_type_schema",
    "run",
    "run_async",
    "run_sync",
]
