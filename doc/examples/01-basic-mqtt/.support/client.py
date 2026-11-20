#!/usr/bin/env python3
"""Make's publisher/subscriber: encrypt/decrypt complete MQTT payloads."""

import json
import logging
import os
import random
import sys
from pathlib import Path

from ships import SHIPS

from pyrophone import Input, Node, Output, cabe, mqtt, node_type, run_sync

# Share the demo's settings when invoked from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from script import (
    CABE_SERVICE,
    MQTT_BROKER,
)

INPUT_TOPIC = "pyrophone-example/S/MARBLE"
OUTPUT_TOPIC = "pyrophone-example/C/GESTALT"
CABE_INPUT_ATTRS = dict(compartment="MARBLE", sensitivity="S")


def default_message() -> str:
    return json.dumps(
        {"hopCount": 0, "shipData": random.choice(SHIPS)},
        separators=(",", ":"),
    )


@node_type
class Message(Node):
    out_port = Output[bytes]()

    async def run(self) -> None:
        payload = os.environ.get("MESSAGE") or default_message()
        print(f"{INPUT_TOPIC} ← {payload}", flush=True)
        await self.out_port.send(payload.encode())


@node_type
class Display(Node):
    in_port = Input[bytes]()

    async def run(self) -> None:
        async for payload in self.in_port:
            sys.stdout.buffer.write(payload + b"\n")
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "MQTT_PORT" in os.environ:
        MQTT_BROKER = {**MQTT_BROKER, "port": int(os.environ["MQTT_PORT"])}
    INPUT_TOPIC = os.getenv("INPUT_TOPIC", INPUT_TOPIC)
    OUTPUT_TOPIC = os.getenv("OUTPUT_TOPIC", OUTPUT_TOPIC)
    if sys.argv[1:] == ["publish"]:
        run_sync(
            Message()
            | cabe.Encapsulator(service=CABE_SERVICE, attrs=CABE_INPUT_ATTRS)
            | mqtt.Sink(**MQTT_BROKER, topic=INPUT_TOPIC)
        )
    elif sys.argv[1:] == ["subscribe"]:
        run_sync(
            mqtt.Source(**MQTT_BROKER, topic=OUTPUT_TOPIC)
            | cabe.Decapsulator(service=CABE_SERVICE)
            | Display()
        )
    else:
        raise SystemExit("usage: client.py publish|subscribe")
