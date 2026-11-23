---
title: CLI
description: Describes the Pyrophone CLI flags.
sidebar:
  order: 2
---

The Pyrophone runtime provides CLI parsing for free, and automatically exposes a number of flags on any Pyrophone program which allows the Pyrophone runtime to be configured.

These flags can be viewed by running a Pyrophone script with `--help`:

```shell
$ python3 script.py --help
```

Some of the most useful flags are:

- `--pp-show-graph`: Print a human-readable description of the produced processing graph before executing it. It takes an optional argument specifying the output format, which defaults to `pretty`. Other supported values are `yaml` and `graphviz`.

- `--pp-dump-graph`: Outputs a machine-readable textual description of the produced processing graph and exits without executing it. This flag differs from `--pp-show-graph` because it exits without running the graph. It takes an optional argument specifying the output format, which, unlike `--pp-show-graph`, defaults to `yaml`.

- `--pp-shell`: Launches the Pyrophone program, but spawns an interactive Python REPL shell on stdio. This allows for dynamic examination, modification and instrumentation of a Pyrophone processing pipeline as it runs.

  [See here for more information on using the shell.](/overview/shell/)
