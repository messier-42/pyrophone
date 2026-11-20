"""MQTT nodes keep protocol transport separate from payload interpretation."""

import asyncio
import importlib
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from pyrophone import (
    Input,
    Node,
    NodeDeclaration,
    Output,
    node_type,
    node_type_schema,
    run,
)


@pytest.fixture(autouse=True)
def clear_transport_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MQTT_USERNAME", "MQTT_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def declare(cls: type[Node], **configuration: object) -> NodeDeclaration:
    return cast(Callable[..., NodeDeclaration], cls)(**configuration)


def test_mqtt_module_import_does_not_require_external_client() -> None:
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.modules['aiomqtt'] = None; "
            "import pyrophone.mqtt; "
            "assert pyrophone.mqtt.Source; assert pyrophone.mqtt.Sink",
        ],
        check=True,
    )


def test_schema_exposes_payload_bytes_and_connection_properties() -> None:
    mqtt = importlib.import_module("pyrophone.mqtt")
    source = node_type_schema(mqtt.Source)
    sink = node_type_schema(mqtt.Sink)
    assert source.outputs["out_port"].type is bytes
    assert sink.inputs["in_port"].type is bytes
    for schema in (source, sink):
        assert schema.properties["topic"].required
        assert schema.properties["host"].type is str
        assert schema.properties["port"].default == 1883
        assert schema.properties["qos"].minimum == 0
        assert schema.properties["qos"].maximum == 2


@pytest.mark.asyncio
async def test_source_forwards_raw_payloads_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mqtt = importlib.import_module("pyrophone.mqtt")
    payloads = [b"not JSON", b"\x00\xff\x01"]
    received: list[bytes] = []
    calls: list[object] = []

    class Client:
        async def subscribe(self, topic: str, *, qos: int) -> None:
            calls.append((topic, qos))

        @property
        def messages(self) -> AsyncIterator[SimpleNamespace]:
            async def messages() -> AsyncIterator[SimpleNamespace]:
                for payload in payloads:
                    yield SimpleNamespace(payload=payload)

            return messages()

    @asynccontextmanager
    async def client(
        host: str, port: int, username: str | None, password: str | None
    ) -> AsyncIterator[Client]:
        calls.append((host, port, username, password))
        try:
            yield Client()
        finally:
            calls.append("closed")

    monkeypatch.setattr(mqtt, "_client", client)

    @node_type
    class Capture(Node):
        in_port = Input[bytes]()

        async def run(self) -> None:
            async for value in self.in_port:
                received.append(value)

    await run(
        declare(
            mqtt.Source,
            host="broker",
            port=18883,
            topic="in",
            qos=2,
            username="admin",
            password="source-secret",
        )
        | declare(Capture)
    )
    assert received == payloads
    assert calls == [("broker", 18883, "admin", "source-secret"), ("in", 2), "closed"]


@pytest.mark.asyncio
async def test_sink_publishes_raw_payloads_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mqtt = importlib.import_module("pyrophone.mqtt")
    payloads = [b"not JSON", b"\x00\xff\x01"]
    calls: list[object] = []

    class Client:
        async def publish(self, topic: str, payload: bytes, *, qos: int) -> None:
            calls.append((topic, payload, qos))

    @asynccontextmanager
    async def client(
        host: str, port: int, username: str | None, password: str | None
    ) -> AsyncIterator[Client]:
        calls.append((host, port, username, password))
        try:
            yield Client()
        finally:
            calls.append("closed")

    monkeypatch.setattr(mqtt, "_client", client)

    @node_type
    class Emit(Node):
        out_port = Output[bytes]()

        async def run(self) -> None:
            for payload in payloads:
                await self.out_port.send(payload)

    await run(
        declare(Emit)
        | declare(
            mqtt.Sink,
            host="broker",
            port=18883,
            topic="out",
            qos=2,
            username="admin",
            password="sink-secret",
        )
    )
    assert calls == [
        ("broker", 18883, "admin", "sink-secret"),
        ("out", payloads[0], 2),
        ("out", payloads[1], 2),
        "closed",
    ]


@pytest.mark.asyncio
async def test_source_cancellation_exits_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mqtt = importlib.import_module("pyrophone.mqtt")
    started, closed = asyncio.Event(), asyncio.Event()

    class Client:
        async def subscribe(self, topic: str, *, qos: int) -> None:
            started.set()

        @property
        def messages(self) -> AsyncIterator[SimpleNamespace]:
            async def messages() -> AsyncIterator[SimpleNamespace]:
                await asyncio.Event().wait()
                yield SimpleNamespace(payload=b"")

            return messages()

    @asynccontextmanager
    async def client(
        host: str, port: int, username: str | None, password: str | None
    ) -> AsyncIterator[Client]:
        try:
            yield Client()
        finally:
            closed.set()

    monkeypatch.setattr(mqtt, "_client", client)

    @node_type
    class Drain(Node):
        in_port = Input[bytes]()

        async def run(self) -> None:
            async for _ in self.in_port:
                pass

    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        graph = tasks.create_task(
            run(declare(mqtt.Source, topic="in") | declare(Drain))
        )
        await started.wait()
        graph.cancel()
        with pytest.raises(asyncio.CancelledError):
            await graph
    assert closed.is_set()


def test_missing_dependency_has_installation_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mqtt = importlib.import_module("pyrophone.mqtt")

    def missing(name: str) -> ModuleType:
        raise ModuleNotFoundError("No module named aiomqtt", name="aiomqtt")

    monkeypatch.setattr(mqtt, "import_module", missing)
    with pytest.raises(ImportError, match=r"Pyrophone\[mqtt\]"):
        mqtt._client("127.0.0.1", 1883)


@pytest.mark.parametrize("credentials", [(None, None), ("admin", "test-secret")])
def test_client_passes_credentials_to_aiomqtt(
    monkeypatch: pytest.MonkeyPatch, credentials: tuple[str | None, str | None]
) -> None:
    mqtt = importlib.import_module("pyrophone.mqtt")
    calls: list[object] = []
    module = ModuleType("aiomqtt")

    def client(host: str, port: int, **kwargs: object) -> object:
        calls.append((host, port, kwargs))
        return object()

    monkeypatch.setattr(module, "Client", client, raising=False)
    monkeypatch.setattr(mqtt, "import_module", lambda name: module)
    mqtt._client("broker", 1883, *credentials)
    assert calls == [
        ("broker", 1883, dict(zip(("username", "password"), credentials, strict=True)))
    ]


@pytest.mark.parametrize(
    ("username", "password", "expected"),
    [
        (None, None, ("env-user", "env-secret")),
        ("custom", None, ("custom", "env-secret")),
        (None, "custom-secret", ("env-user", "custom-secret")),
        ("", "", ("", "")),
    ],
)
def test_credentials_default_from_environment_at_connection_time(
    monkeypatch: pytest.MonkeyPatch,
    username: str | None,
    password: str | None,
    expected: tuple[str, str],
) -> None:
    mqtt = importlib.import_module("pyrophone.mqtt")
    declaration = declare(
        mqtt.Source, topic="test", username=username, password=password
    )
    monkeypatch.setenv("MQTT_USERNAME", "env-user")
    monkeypatch.setenv("MQTT_PASSWORD", "env-secret")
    calls: list[object] = []
    module = ModuleType("aiomqtt")

    def client(host: str, port: int, **options: object) -> object:
        calls.append((host, port, options))
        return object()

    monkeypatch.setattr(module, "Client", client, raising=False)
    monkeypatch.setattr(mqtt, "import_module", lambda name: module)
    mqtt._client("broker", 1883, username, password)
    assert calls == [
        ("broker", 1883, {"username": expected[0], "password": expected[1]})
    ]
    assert declaration.configuration["username"] == username
    assert declaration.configuration["password"] == password
    assert declaration.configuration["port"] == 1883
