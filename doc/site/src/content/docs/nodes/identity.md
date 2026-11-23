---
title: Identity
description: The general-purpose identity transform node types.
sidebar:
  order: 1
---

### Description

The `Identity` node type is a generic, transform-style node type which does not modify its input. It is a trivial no-op transform node.

`IdentityBytes` is an alias for `Identity[bytes]`.

### Usage

```python
from pyrophone.script import *

@main
def graph():
    return (
        ... |
        IdentityBytes() |
        ...
    )
```