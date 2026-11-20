"""The MQTT demo increments hopCount and changes CABE attributes."""

import json
import runpy
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from pyrophone import Input, Node, NodeDeclaration, Output, node_type, run

SCRIPT = Path(__file__).resolve().parents[1] / "doc/examples/01-basic-mqtt/script.py"


def declare(cls: type[Node], **configuration: object) -> NodeDeclaration:
    return cast(Callable[..., NodeDeclaration], cls)(**configuration)


async def transform(
    value: dict[str, object], **configuration: object
) -> dict[str, object]:
    namespace = runpy.run_path(str(SCRIPT.with_name("adder.py")))
    adder = cast(type[Node], namespace["Adder"])
    results: list[dict[str, object]] = []

    @node_type
    class Source(Node):
        out_port = Output[bytes]()

        async def run(self) -> None:
            await self.out_port.send(json.dumps(value).encode())

    @node_type
    class Sink(Node):
        in_port = Input[bytes]()

        async def run(self) -> None:
            async for item in self.in_port:
                results.append(json.loads(item))

    await run(declare(Source) | declare(adder, **configuration) | declare(Sink))
    assert len(results) == 1
    return results[0]


@pytest.mark.asyncio
async def test_increment_preserves_other_json_properties_and_original() -> None:
    value: dict[str, object] = {
        "value": 0,
        "name": "a counter",
        "metadata": {"enabled": True, "items": [1, None, "hello"]},
        "nothing": None,
    }
    result = await transform(value)
    assert result == {**value, "value": 1}
    assert value["value"] == 0
    assert result is not value


@pytest.mark.asyncio
@pytest.mark.parametrize(("hop_count", "expected"), [(0, 1), (-2, -1), (1.5, 2.5)])
async def test_numeric_value(hop_count: int | float, expected: int | float) -> None:
    assert await transform({"value": hop_count}) == {"value": expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 3, -2])
async def test_configured_amount_preserves_other_properties(amount: int) -> None:
    value: dict[str, object] = {"value": 7, "metadata": {"name": "demo"}}
    assert await transform(value, amount=amount) == {**value, "value": 7 + amount}
    assert value["value"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{}, {"value": True}, {"value": "0"}])
async def test_invalid_value_fails_with_context(value: dict[str, object]) -> None:
    with pytest.raises(ExceptionGroup) as caught:
        await transform(value)
    assert any(
        isinstance(error.__cause__, ValueError) and "value" in str(error.__cause__)
        for error in caught.value.exceptions
    )


@pytest.mark.asyncio
async def test_configured_attribute_preserves_other_numbers() -> None:
    value: dict[str, object] = {"hopCount": 0, "value": 99, "other": 42}
    assert await transform(value, amount=1, attributeName="hopCount") == {
        **value,
        "hopCount": 1,
    }


@pytest.mark.asyncio
async def test_missing_configured_attribute_names_field_in_error() -> None:
    with pytest.raises(ExceptionGroup) as caught:
        await transform({"value": 99}, attributeName="hopCount")
    assert any(
        isinstance(error.__cause__, ValueError) and "hopCount" in str(error.__cause__)
        for error in caught.value.exceptions
    )


def test_make_publish_preserves_literal_json(tmp_path: Path) -> None:
    client = tmp_path / "client.py"
    client.write_text(
        "import os, sys\nassert sys.argv[1] == 'publish'\nprint(os.environ['MESSAGE'])\n"
    )
    payload = json.dumps({"hopCount": 0, "text": "O'Brien's $HOME and $(literal)"})
    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-s",
            "-C",
            str(SCRIPT.parent),
            "publish",
            f"CLIENT={shlex.join([sys.executable, str(client)])}",
            f"MESSAGE={payload}",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == payload


def test_demo_graph_has_cabe_on_both_sides_of_adder() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--pp-dump-graph=yaml"],
        capture_output=True,
        text=True,
        check=True,
    )
    import yaml

    document = yaml.safe_load(result.stdout)
    nodes = [
        node
        for node in document["nodes"]
        if node["type"]
        not in (
            "pyrophone.nodes.PrintBytes",
            "pyrophone.nodes.PrintText",
            "pyrophone.cabe.Printer",
        )
    ]
    assert [node["type"].rsplit(".", 1)[-1] for node in nodes] == [
        "Source",
        "Decapsulator",
        "Adder",
        "Encapsulator",
        "Sink",
    ]
    assert nodes[2]["configuration"] == {
        "amount": 1,
        "attributeName": "hopCount",
    }
    decap, encap = nodes[1], nodes[3]
    assert decap["configuration"]["service"] == encap["configuration"]["service"]
    assert encap["configuration"]["attrs"] == {
        "sensitivity": "C",
        "compartment": "GESTALT",
    }
    assert len(document["edges"]) == len(document["nodes"]) - 1


def test_default_ship_messages_select_from_static_fleet() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
from unittest.mock import patch
import client

before = json.dumps(client.SHIPS)
with patch.object(client.random, 'choice', side_effect=client.SHIPS) as choose:
    messages = [json.loads(client.default_message()) for _ in client.SHIPS]
assert choose.call_count == 10
assert all(call.args == (client.SHIPS,) for call in choose.call_args_list)
assert json.dumps(client.SHIPS) == before
print(json.dumps([client.CABE_INPUT_ATTRS, client.SHIPS, messages]))
""",
        ],
        cwd=SCRIPT.parent / ".support",
        capture_output=True,
        text=True,
        check=True,
    )
    attrs, ships, messages = json.loads(result.stdout)
    assert attrs == {"sensitivity": "S", "compartment": "MARBLE"}
    assert len(ships) == len({ship["name"] for ship in ships}) == 10
    assert messages == [{"hopCount": 0, "shipData": ship} for ship in ships]
    for ship in ships:
        assert set(ship) == {"name", "outdoorTemperature", "location"}
        assert -10 <= ship["outdoorTemperature"] <= 35
        lat, lon = ship["location"]
        assert -90 <= lat <= 90 and -180 <= lon <= 180
