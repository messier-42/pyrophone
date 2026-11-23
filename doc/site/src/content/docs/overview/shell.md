---
title: Live shell, inspection and tracing
description: Describes the Pyrophone live shell.
sidebar:
  order: 5
---

The Pyrophone live shell is a Python REPL environment which can run in the foreground while executing a Pyrophone program. It can be accessed for any Pyrophone script by launching the script with the flag `--pp-shell`. The Pyrophone script will run in the background, and a Python REPL enables examination, instrumentation and modification of the Pyrophone pipeline as it runs.

To exit the shell and terminate the Pyrophone program, send EOF by pressing Ctrl-D.

## Locals

The following locals are bound in the REPL environment:

- `graph` is the graph object provided by the user's Pyrophone script. You can examine nodes and edges with `graph.nodes` and `graph.edges`, which are tuples of the graph's nodes and edges respectively.

- `compiled_graph` is the low-level graph representation which was compiled by the Pyrophone runtime. You can examine the nodes and edges with `compiled_graph.nodes` and `compiled_graph.edges` respectively.

- `runtime` is the runtime state of the Pyrophone runtime, including runtime instantiations of the nodes in the Pyrophone graph. You can examine the nodes with `runtime.nodes`.

## The `print()` method

Each graph, node or edge-like object has a `print()` method which can produce a multi-line human readable description of the object. The usual Python `repr()` function can also be used, but produces a shorter single-line summary.

For example, `graph.print()` prints a description of the user specified graph. `runtime.print()` prints the equivalent runtime instance state.

## Live tracing

You can trace data being passed on a port of a node at runtime without having to terminate or restart a Pyrophone program:

```python
>>> uppercase_node = runtime.nodes[1]

>>> uppercase_node
<NodeHandle Uppercase#c97dcec9>

>>> uppercase_node.print()
NodeHandle: __main__.Uppercase
  ID: ...
  Properties:
    (none)
  Inputs:
    in_port: str
  Outputs:
    out_port: str

>>> uppercase_node.in_port
<PortHandle Uppercase#c97dcec9.in_port (input)>

# Add trace callbacks for both the input
# and output of the Uppercase node.
>>> in_trace = uppercase_node.in_port.trace(lambda v: print('BEFORE:', v))
>>> out_trace = uppercase_node.out_port.trace(lambda v: print('AFTER:', v))

# Stop the traces once no longer needed.
>>> in_trace.close()
>>> out_trace.close()
```

## Live property modification

You can modify properties on nodes live:

```python
>>> adder_node = runtime.nodes[1]
>>> adder_node.amount
1
>>> adder_node.amount = 42
```