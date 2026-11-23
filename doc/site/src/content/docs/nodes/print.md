---
title: Print
description: The general-purpose printer node types.
sidebar:
  order: 2
---

### Description

The `Print`, `PrintBytes` and `PrintText` node types provide transform-style nodes which do not modify their input but pass it through as-is, but which produce diagnostic output over all data passed through. They can be inserted into a graph to provide diagnostic output.

### Usage

The usages of `Print`, `PrintBytes` and `PrintText` are identical.

`Print` formats an arbitrary value in a normal Python way before printing it.

`PrintBytes` accepts `bytes` and produces the `repr()`-format representation of a `bytes` value.

`PrintText` accepts either `str` or `bytes`. It prints any received `str` values as-is. It opportunistically tries to decode `bytes` values as UTF-8. If the string decodes successfully as UTF-8, it is printed without escaping; otherwise, the `repr()`-format representation of the original `bytes` value is printed.

```python
from pyrophone.script import *

@main
def graph():
    return (
        ... |
        Print() |
        ...
    )
```