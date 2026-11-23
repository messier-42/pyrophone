---
title: JQ
description: The JQ node type.
sidebar:
  order: 10
---

:::note
This node type requires the `jq` optional dependencies to be installed:

```shell
$ python3 -m pip install 'Pyrophone[jq]'
```

You can still construct and define `JQ` nodes without installing the dependencies, but execution will not be possible.
:::

### Description

The `JQ` node type applies the same filter language as defined b y the `jq(1)` command-line tool to an input JSON value, and outputs another JSON value produced by the specified `jq` expression.

It is a transform node, with a single input and output port, each accepting UTF-8 encoded bytestrings.

### Usage

```python
from pyrophone.script import *

@main
def graph():
    return (
        ... |
        JQ(expr=".headers") |
        ...
    )
```