"""Shared text inspection helpers, independent of graph construction."""

from collections.abc import Mapping
from pprint import pformat
from typing import TextIO

from ._schema import NodeTypeSchema


class Printable:
    """Print a detailed description to stdout or a supplied text stream."""

    def print(self, *, file: TextIO | None = None) -> None:
        """Write a pretty multiline description, followed by a newline."""
        print(self._describe(), file=file)

    def _describe(self) -> str:
        raise NotImplementedError


def type_name(spec: object) -> str:
    return spec.__name__ if isinstance(spec, type) else str(spec)


def node_details(
    node_type: type,
    configuration: Mapping[str, object],
    schema: NodeTypeSchema,
    *,
    kind: str = "Node",
    node_id: str | None = None,
) -> str:
    lines = [f"{kind}: {node_type.__module__}.{node_type.__qualname__}"]
    if node_id is not None:
        lines.append(f"  ID: {node_id}")
    lines.append("  Properties:")
    for name, value in configuration.items():
        value_lines = pformat(value, width=68, sort_dicts=False).splitlines()
        lines.append(f"    {name}: {value_lines[0]}")
        lines.extend(f"      {line}" for line in value_lines[1:])
    if not configuration:
        lines.append("    (none)")
    for label, ports in (("Inputs", schema.inputs), ("Outputs", schema.outputs)):
        lines.append(f"  {label}:")
        for name, port in ports.items():
            default = " (default)" if port.default else ""
            lines.append(f"    {name}: {type_name(port.type)}{default}")
        if not ports:
            lines.append("    (none)")
    return "\n".join(lines)
