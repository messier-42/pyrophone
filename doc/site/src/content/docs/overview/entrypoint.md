---
title: Boilerplate and Entrypoints
description: Describes the Pyrophone boilerplate and entrypoint options.
sidebar:
  order: 6
---

## Importing Pyrophone

The `pyrophone.script` module provides a useful namespace to import which exposes the most important Pyrophone definitions for a Pyrophone script:

```python
from pyrophone.script import *
```

## Defining your graph function

A Pyrophone script must define a function which returns a constructed Pyrophone graph definition. The recommended way to expose this function is using the `@pyrophone.main` decorator (available simply as `@main` if importing `pyrophone.script`):

```python
@main
def graph():
    return Source() | Foo() | Sink()
```

This has the advantage of providing the Pyrophone CLI driver and giving your Pyrophone script the benefit of the runtime's automatic CLI processing and runtime configuration for free.

Annotating a function with `@pyrophone.main` will cause the graph to be executed automatically if the caller is the `__main__` module, similar to the standard `if __name__ == "__main__":` idiom. The user's graph construction function remains available for consumption as an import without automatically executing it.

## `pyrophone.run_async` and `pyrophone.run_sync`

Alternatively, the Pyrophone runtime can be launched within the context of a larger program using an already-constructed graph representation. `pyrophone.run_async` and `pyrophone.run_sync` accept a graph or graph constructor function which (when executed) returns a graph.