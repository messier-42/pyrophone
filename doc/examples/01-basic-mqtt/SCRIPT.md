# Pyrophone MQTT Demo (Speaker Script)

## Preparation

### Stack

```shell
$ cp .support/script-stage0.py ./script.py
$ make setup up   # Bring mosquitto, khaled stack up
$ make tmux       # Launch tmux
```

### tmux shells

Bottom:
- `./script.sh [--pp-shell]`

Top left:
- `subscribe`

Top right:
- `publish` x3

Confirm working. Clear each pane and relaunch each command.

## Speaking Script

### 1. Orientation

- Explain scenario using slides (diagram).

- Cut to tmux shell. Reiterate, explain role of panes.

- Demonstrate `publish`.

- Cut briefly to MQTT viewer, showing that CABE encryption is in use. Highlight
  attributes in hex dump on input and output, showing difference.

- Explain our problem: we want to redact positions so less sensitive data can
  be relayed to a different context.

### 2. Initial Script

- Show and explain `script.py` (stage 1).

- Explain the idea of graphs, nodes, edges, filters. Show diagram from slides
  indicating current graph.

- Explain that we have a JQ filter and add the JQ line.

  ```python
  | JQ(expr="{hopCount, shipData: (.shipData | {name, outdoorTemperature})}")
  ```

- Rerun and show that redaction now occurs.

### 3. Visibility

- Add `PrintText()`, `PrintBytes()`, `cabe.Printer()` for exposition as desired and rerun.
  Explain that these are just filters.

- Do this several times, adding a print command to show a new part in the chain.

### 4. Custom Nodes

- Add `Adder(amount=1, attributeName="hopCount")`. Explain that this is a custom node.

- Show `adder.py` and exhibit ease of implementing custom nodes.

- Show that the hop count increase works.

### 5. Dump Commands

- Note how `script.py` doesn't require much CLI cruft.

- Show `--help`.

- Exhibit the pretty dump command.

### 6. The Shell

- Relaunch `script.py` with `--pp-shell`.

- `runtime` is the runtime instance (`runtime.nodes`)

- `graph` is the high level graph the user expressed (`graph.nodes`, `graph.edges`)

- Explore and demonstrate the graph, nodes, edge objects. Show how it's instrumentable.

- Graphs, nodes, edges each have `x.print()`

### 7. Live Param Changes

- In the shell:

  ```
  runtime.nodes
  adder = runtime.nodes[X]
  adder.print()
  adder.amount = 42
  ```

- Publish again to show it works

### 8. Live Tracing

Remove most print filters from `script.py`.

```
runtime
runtime.nodes
adder = runtime.nodes[X]

in_trace = adder.in_port.trace(lambda v: print('BEFORE:', v))
out_trace = adder.out_port.trace(lambda v: print('AFTER:', v))
```

Publish, show traces.

### 9. Graphviz

Optionally use `make graphviz` to show a Graphviz rendering. Show how it
changes after adding more filters to `script.py`.

### 10. Optional — Custom Nodes Redux

Go into src/pyrophone and exhibit some of the helper node base classes, showing
how `JSONTransform` is built on top of `Transform`, using it as an example of
how functionality can be easily composed in a principled way. Optionally walk
through some of the architecture docs.
