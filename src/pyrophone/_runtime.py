"""One-shot execution of validated graph snapshots with structured task ownership."""

import asyncio
from dataclasses import dataclass, field

from ._channels import Channel, ReceiveEndpoint, SendEndpoint
from ._compile import CompiledNode, compile_graph
from ._exceptions import NodeExecutionError
from ._graph import Graph
from ._node import Node, _bind_node


@dataclass
class _Bindings:
    inputs: dict[str, ReceiveEndpoint[object]] = field(default_factory=dict)
    outputs: dict[str, SendEndpoint[object]] = field(default_factory=dict)

    async def close(self) -> None:
        for output in self.outputs.values():
            await output.close()
        for input_port in self.inputs.values():
            await input_port.close()


async def _execute(node: CompiledNode, instance: Node, bindings: _Bindings) -> None:
    try:
        await instance.run()
    except Exception as error:
        raise NodeExecutionError(node.id, node.node_type) from error
    finally:
        await bindings.close()


async def run_async(graph: Graph) -> None:
    """Run a fresh instance of each node after validating the entire graph.

    Normal return closes a node's outputs and inputs. A failed node cancels its
    siblings; cancellation awaits their cooperative cleanup. Run failures appear
    in TaskGroup exception groups containing one or more NodeExecutionErrors,
    each retaining the original exception as its cause. Initialization failures
    raise NodeExecutionError directly, before any node run tasks are started.

    Nodes should own asynchronous resources inside run(), using async context
    managers or try/finally. The runtime closes its endpoints, but cannot unwind
    arbitrary resources acquired by user initializers. There are no forced
    cancellation timeouts, restart policies, or background runtime tasks.
    """
    compiled = compile_graph(graph)
    bindings = {node.id: _Bindings() for node in compiled.nodes}
    channels: list[Channel[object]] = []
    try:
        for edge in compiled.edges:
            channel = Channel[object]()
            channels.append(channel)
            bindings[edge.source_id].outputs[edge.source_port] = channel.output
            bindings[edge.destination_id].inputs[edge.destination_port] = channel.input
        instances: list[Node] = []
        for node in compiled.nodes:
            ports = bindings[node.id]
            try:
                instance = _bind_node(
                    node.node_type, node.configuration, ports.inputs, ports.outputs
                )
            except Exception as error:
                raise NodeExecutionError(node.id, node.node_type) from error
            instances.append(instance)
        async with asyncio.TaskGroup() as tasks:
            for node, instance in zip(compiled.nodes, instances, strict=True):
                tasks.create_task(
                    _execute(node, instance, bindings[node.id]),
                    name=f"pyrophone:{node.node_type.__name__}:{node.id}",
                )
    finally:
        # Covers initialization failure and tasks cancelled before first execution.
        for channel in channels:
            await channel.output.close()
