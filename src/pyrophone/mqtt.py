"""MQTT payload sources and sinks, backed by the optional ``mqtt`` extra.

Importing this module and declaring graphs needs no MQTT client installation.
Install ``Pyrophone[mqtt]`` to execute these nodes. Payloads are bytes; decoding
and encoding belong in application transforms.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from importlib import import_module
from typing import Protocol, cast

from ._node import Node, node_type
from ._ports import Input, Output
from ._properties import Property

__all__ = ["Sink", "Source"]

_logger = logging.getLogger(__name__)


class _Message(Protocol):
    @property
    def payload(self) -> bytes: ...


class _Client(Protocol):
    """The small client interface used without importing optional dependencies."""

    @property
    def messages(self) -> AsyncIterator[_Message]: ...

    async def subscribe(self, topic: str, *, qos: int) -> object: ...

    async def publish(self, topic: str, payload: bytes, *, qos: int) -> None: ...


def _client(
    host: str, port: int, username: str | None = None, password: str | None = None
) -> AbstractAsyncContextManager[_Client]:
    try:
        aiomqtt = import_module("aiomqtt")
    except ModuleNotFoundError as error:
        if error.name != "aiomqtt":
            raise
        raise ImportError(
            "MQTT nodes require optional dependencies: pip install 'Pyrophone[mqtt]'"
        ) from error
    return cast(
        AbstractAsyncContextManager[_Client],
        aiomqtt.Client(
            host,
            port,
            username=username if username is not None else os.getenv("MQTT_USERNAME"),
            password=password if password is not None else os.getenv("MQTT_PASSWORD"),
        ),
    )


class _MQTTNode(Node):
    host = Property[str](
        default="127.0.0.1",
        title="Broker host",
        description="Hostname or address of the MQTT broker.",
    )
    port = Property[int](
        default=1883,
        title="Broker port",
        description="TCP port on which the MQTT broker is listening.",
        minimum=1,
        maximum=65535,
    )
    username = Property[str | None](
        default=None, description="MQTT username; None uses MQTT_USERNAME at startup."
    )
    password = Property[str | None](
        default=None, description="MQTT password; None uses MQTT_PASSWORD at startup."
    )
    topic = Property[str](description="MQTT topic to subscribe to or publish on.")
    qos = Property[int](
        default=1,
        title="Quality of service",
        description="MQTT QoS level for this broker connection's messages.",
        minimum=0,
        maximum=2,
    )


@node_type
class Source(_MQTTNode):
    """Subscribe to an MQTT topic and emit raw message payloads.

    Broker disconnection fails the node; reconnection and application-level
    acknowledgement policies are not supplied by this node.
    """

    out_port = Output[bytes](description="MQTT message payloads, without decoding.")

    async def run(self) -> None:
        async with _client(
            self.host, self.port, self.username, self.password
        ) as client:
            await client.subscribe(self.topic, qos=self.qos)
            _logger.info("Subscribed to %s", self.topic)
            async for message in client.messages:
                await self.out_port.send(message.payload)


@node_type
class Sink(_MQTTNode):
    """Publish raw payloads to an MQTT topic, without retaining messages."""

    in_port = Input[bytes](description="Raw MQTT payloads to publish.")

    async def run(self) -> None:
        async with _client(
            self.host, self.port, self.username, self.password
        ) as client:
            async for payload in self.in_port:
                await client.publish(self.topic, payload, qos=self.qos)
