"""CABE adapters preserve byte framing and own their optional clients."""

import asyncio
import importlib
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace

import pytest

import pyrophone as pp


@pytest.fixture(autouse=True)
def clear_transport_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CABE_CERTIFICATE_FILE", "CABE_KEY_FILE", "CABE_CA_FILE"):
        monkeypatch.delenv(name, raising=False)


def test_import_and_graph_declaration_without_pycabe() -> None:
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.modules['cabe'] = None; "
            "from pyrophone.script import cabe; "
            "g = cabe.Printer() | cabe.Decapsulator(service={'url':'https://keys/'}) | "
            "cabe.Encapsulator(service={'url':'https://keys/'}, attrs={'sensitivity':'S'}); "
            "assert len(g.nodes) == 3",
        ],
        check=True,
    )


@pytest.mark.asyncio
async def test_roundtrip_uses_one_client_per_node_and_closes_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cabe = importlib.import_module("pyrophone.cabe")
    calls: list[object] = []
    payloads = [b"", b"\x00\xff\n", b'{"count":0}']
    received: list[bytes] = []

    class Codec:
        async def encapsulate(self, payload: bytes, attrs: dict[str, object]) -> bytes:
            calls.append(dict(attrs))
            return b"envelope:" + payload

        async def decapsulate(self, payload: bytes) -> bytes:
            assert payload.startswith(b"envelope:")
            return payload.removeprefix(b"envelope:")

    @asynccontextmanager
    async def service(settings: dict[str, object]) -> AsyncIterator[Codec]:
        calls.append(settings)
        try:
            yield Codec()
        finally:
            calls.append("closed")

    monkeypatch.setattr(cabe, "_service", service)

    @pp.node_type
    class Emit(pp.Node):
        out_port = pp.Output[bytes]()

        async def run(self) -> None:
            for payload in payloads:
                await self.out_port.send(payload)

    @pp.node_type
    class Capture(pp.Node):
        in_port = pp.Input[bytes]()

        async def run(self) -> None:
            async for payload in self.in_port:
                received.append(payload)

    settings = {"url": "https://keys/"}
    graph = (
        pp.NodeDeclaration(Emit)
        | pp.NodeDeclaration(
            cabe.Encapsulator, {"service": settings, "attrs": {"sensitivity": "S"}}
        )
        | pp.NodeDeclaration(cabe.Decapsulator, {"service": settings})
        | pp.NodeDeclaration(Capture)
    )
    await pp.run_async(graph)
    assert received == payloads
    assert calls.count(settings) == 2
    assert calls.count({"sensitivity": "S"}) == len(payloads)
    assert calls.count("closed") == 2
    for cls in (cabe.Encapsulator, cabe.Decapsulator):
        schema = pp.node_type_schema(cls)
        assert schema.inputs["in_port"].type is bytes
        assert schema.outputs["out_port"].type is bytes
        assert schema.properties["service"].required


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_or_cancellation_closes_client_without_plaintext_output(
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    cabe = importlib.import_module("pyrophone.cabe")
    started, closed = asyncio.Event(), asyncio.Event()

    class Codec:
        async def decapsulate(self, payload: bytes) -> bytes:
            started.set()
            if cancel:
                await asyncio.Event().wait()
            raise ValueError("authentication failed")

    @asynccontextmanager
    async def service(settings: dict[str, object]) -> AsyncIterator[Codec]:
        try:
            yield Codec()
        finally:
            closed.set()

    monkeypatch.setattr(cabe, "_service", service)

    @pp.node_type
    class Emit(pp.Node):
        out_port = pp.Output[bytes]()

        async def run(self) -> None:
            await self.out_port.send(b"invalid")

    @pp.node_type
    class Capture(pp.Node):
        in_port = pp.Input[bytes]()

        async def run(self) -> None:
            async for _ in self.in_port:
                pytest.fail("unauthenticated bytes escaped")

    graph = (
        pp.NodeDeclaration(Emit)
        | pp.NodeDeclaration(cabe.Decapsulator, {"service": {"url": "https://keys/"}})
        | pp.NodeDeclaration(Capture)
    )
    async with asyncio.timeout(2):
        task = asyncio.create_task(pp.run_async(graph))
        await started.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ExceptionGroup, match="TaskGroup"):
                await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_adapter_calls_public_pycabe_api(monkeypatch: pytest.MonkeyPatch) -> None:
    cabe = importlib.import_module("pyrophone.cabe")
    calls: list[object] = []

    class Envelope:
        @classmethod
        def decode(cls, payload: bytes, *, wire_limit: int | None = None) -> "Envelope":
            calls.append(("decode", payload, wire_limit))
            return cls()

        def encode(self) -> bytes:
            return b"wire"

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: object) -> None:
            calls.append("closed")

        async def encapsulate(self, message: SimpleNamespace) -> Envelope:
            calls.append(("message", message.payload, message.attributes))
            return Envelope()

        async def decapsulate(self, envelope: Envelope) -> SimpleNamespace:
            assert isinstance(envelope, Envelope)
            return SimpleNamespace(payload=b"plain")

    api, tls_module = ModuleType("cabe"), ModuleType("cabe.tls")

    def client(url: str, **kwargs: object) -> Client:
        calls.append((url, kwargs))
        return Client()

    def tls(**kwargs: object) -> object:
        calls.append(kwargs)
        return "tls-config"

    def message(payload: bytes, attributes: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(payload=payload, attributes=attributes)

    monkeypatch.setattr(api, "Client", client, raising=False)
    monkeypatch.setattr(api, "Message", message, raising=False)
    monkeypatch.setattr(api, "Envelope", Envelope, raising=False)
    monkeypatch.setattr(tls_module, "FileTLS", tls, raising=False)
    monkeypatch.setattr(
        cabe, "import_module", lambda name: {"cabe": api, "cabe.tls": tls_module}[name]
    )
    async with cabe._service(
        {
            "url": "https://keys/ckap",
            "tls": {"cert_file": "cert", "key_file": "key"},
            "timeout": 5,
            "wire_limit": 1024,
        }
    ) as codec:
        assert await codec.encapsulate(b"plain", {"sensitivity": "S"}) == b"wire"
        assert await codec.decapsulate(b"wire") == b"plain"
    assert calls == [
        {"cert_file": "cert", "key_file": "key"},
        ("https://keys/ckap", {"tls": "tls-config", "timeout": 5, "wire_limit": 1024}),
        ("message", b"plain", {"sensitivity": "S"}),
        ("decode", b"wire", 1024),
        "closed",
    ]


@pytest.mark.asyncio
async def test_missing_dependency_reports_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cabe = importlib.import_module("pyrophone.cabe")

    def missing(name: str) -> ModuleType:
        raise ModuleNotFoundError("missing cabe", name="cabe")

    monkeypatch.setattr(cabe, "import_module", missing)
    with pytest.raises(ImportError, match=r"Pyrophone\[cabe\]"):
        async with cabe._service({"url": "https://keys/"}):
            pytest.fail("missing dependency accepted")


@pytest.mark.asyncio
@pytest.mark.parametrize("service", [{}, {"url": ""}, {"url": "https://keys/"}])
async def test_invalid_service_settings_fail_before_opening_client(
    monkeypatch: pytest.MonkeyPatch, service: dict[str, object]
) -> None:
    cabe = importlib.import_module("pyrophone.cabe")
    monkeypatch.setattr(cabe, "import_module", lambda name: ModuleType(name))
    with pytest.raises(pp.ConfigurationError, match="service"):
        async with cabe._service(service):
            pytest.fail("invalid service accepted")


async def print_envelopes(payloads: list[bytes]) -> list[bytes]:
    cabe = importlib.import_module("pyrophone.cabe")
    received: list[bytes] = []

    @pp.node_type
    class Emit(pp.Node):
        out_port = pp.Output[bytes]()

        async def run(self) -> None:
            for payload in payloads:
                await self.out_port.send(payload)

    @pp.node_type
    class Capture(pp.Node):
        in_port = pp.Input[bytes]()

        async def run(self) -> None:
            async for payload in self.in_port:
                received.append(payload)

    await pp.run_async(
        pp.NodeDeclaration(Emit)
        | pp.NodeDeclaration(cabe.Printer)
        | pp.NodeDeclaration(Capture)
    )
    return received


@pytest.mark.asyncio
async def test_print_inspects_real_envelope_headers_without_client(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = pytest.importorskip("cabe")
    cbor = pytest.importorskip("cborx")

    def no_client(*args: object, **kwargs: object) -> None:
        pytest.fail("header inspection must not create a key-service client")

    monkeypatch.setattr(api, "Client", no_client)
    protected = {
        1: 1,
        3: "application/json",
        "CABE_AttributeSet": api.AttributeSet(
            {"sensitivity": "S", "compartment": "MARBLE"}
        ).to_cbor(),
        "CABE_LeaseRef": b"lease",
        "extension": "first\nsecond\r\x1b[31m",
    }
    wire = cbor.dumps(
        cbor.CBORTag(
            16,
            [
                cbor.dumps(protected),
                {6: b"\x01", "extra": [1, {"binary": b"\x00\xff"}]},
                b"ciphertext-not-for-printing",
            ],
        )
    )
    received = await print_envelopes([wire, wire])
    assert len(received) == 2
    assert all(item is wire for item in received)
    output = capsys.readouterr()
    lines = output.out.splitlines()
    assert len(lines) == 2 and lines[0] == lines[1]
    line = lines[0]
    assert line.startswith(
        'CABE Envelope: Attributes=(compartment="MARBLE", sensitivity="S"), '
        'LeaseRef=6c65617365, content_type="application/json", '
    )
    assert (
        "protected" not in line and "algorithm" not in line and "partial_iv" not in line
    )
    assert "extra=[1, {'binary': b'\\x00\\xff'}]" in line
    assert "first\\nsecond\\r\\u001b[31m" in line
    assert "ciphertext-not-for-printing" not in line
    assert output.err == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference", "display"),
    [
        (b"\xde\xad\xbe\xef", "deadbeef"),
        (
            bytes.fromhex("deadbeef" + "00" * 16 + "beef"),
            "deadbeef" + "00" * 16 + "beef",
        ),
    ],
)
async def test_print_concise_envelope_format(
    reference: bytes, display: str, capsys: pytest.CaptureFixture[str]
) -> None:
    api = pytest.importorskip("cabe")
    cbor = pytest.importorskip("cborx")
    wire = cbor.dumps(
        [
            cbor.dumps(
                {
                    1: 1,
                    "CABE_LeaseRef": reference,
                    "CABE_AttributeSet": api.AttributeSet(
                        {"sensitivity": "C", "compartment": "GESTALT"}
                    ).to_cbor(),
                }
            ),
            {6: b"\x01", 42: "unknown"},
            bytes(16),
        ]
    )
    await print_envelopes([wire])
    assert capsys.readouterr().out == (
        'CABE Envelope: Attributes=(compartment="GESTALT", sensitivity="C"), '
        f'LeaseRef={display}, 42="unknown"\n'
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", [b"invalid", b"\xa0", b"\x83\x40\xa0\x40"])
async def test_print_rejects_invalid_envelopes_without_printing(
    wire: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("cabe")
    with pytest.raises(ExceptionGroup):
        await print_envelopes([wire])
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_print_missing_dependency_reports_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cabe = importlib.import_module("pyrophone.cabe")

    def missing(name: str) -> ModuleType:
        raise ModuleNotFoundError("missing cabe", name="cabe")

    monkeypatch.setattr(cabe, "import_module", missing)
    with pytest.raises(ExceptionGroup) as caught:
        await print_envelopes([b"wire"])
    assert any(
        isinstance(error.__cause__, ImportError)
        and "Pyrophone[cabe]" in str(error.__cause__)
        for error in caught.value.exceptions
    )


def test_print_has_bytes_ports_and_no_required_configuration() -> None:
    cabe = importlib.import_module("pyrophone.cabe")
    schema = pp.node_type_schema(cabe.Printer)
    assert schema.inputs["in_port"].type is bytes
    assert schema.outputs["out_port"].type is bytes
    assert not schema.properties


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured_tls", "expected_tls"),
    [
        (None, {"cert_file": "env-cert", "key_file": "env-key", "ca_file": "env-ca"}),
        (
            {"cert_file": "custom-cert"},
            {"cert_file": "custom-cert", "key_file": "env-key", "ca_file": "env-ca"},
        ),
        (
            {"cert_file": "cert", "key_file": "key", "ca_file": None},
            {"cert_file": "cert", "key_file": "key", "ca_file": None},
        ),
    ],
)
async def test_tls_paths_default_from_environment_at_service_start(
    monkeypatch: pytest.MonkeyPatch,
    configured_tls: dict[str, object] | None,
    expected_tls: dict[str, object],
) -> None:
    from copy import deepcopy

    cabe = importlib.import_module("pyrophone.cabe")
    settings: dict[str, object] = {"url": "https://keys/ckap"}
    if configured_tls is not None:
        settings["tls"] = configured_tls
    before = deepcopy(settings)
    declaration = pp.NodeDeclaration(cabe.Decapsulator, {"service": settings})
    for name, value in (
        ("CABE_CERTIFICATE_FILE", "env-cert"),
        ("CABE_KEY_FILE", "env-key"),
        ("CABE_CA_FILE", "env-ca"),
    ):
        monkeypatch.setenv(name, value)

    @asynccontextmanager
    async def client(url: str, **options: object) -> AsyncIterator[SimpleNamespace]:
        assert url == settings["url"]
        assert options == {"tls": expected_tls}
        yield SimpleNamespace()

    def tls(**options: object) -> dict[str, object]:
        return options

    api, tls_module = ModuleType("cabe"), ModuleType("cabe.tls")
    monkeypatch.setattr(api, "Client", client, raising=False)
    monkeypatch.setattr(tls_module, "FileTLS", tls, raising=False)
    monkeypatch.setattr(
        cabe, "import_module", lambda name: {"cabe": api, "cabe.tls": tls_module}[name]
    )
    async with cabe._service(settings):
        pass
    assert settings == before
    assert declaration.configuration["service"] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("provided", [None, "CABE_CERTIFICATE_FILE", "CABE_KEY_FILE"])
async def test_missing_tls_environment_fails_before_opening_client(
    monkeypatch: pytest.MonkeyPatch, provided: str | None
) -> None:
    cabe = importlib.import_module("pyrophone.cabe")
    for name in ("CABE_CERTIFICATE_FILE", "CABE_KEY_FILE", "CABE_CA_FILE"):
        monkeypatch.delenv(name, raising=False)
    if provided:
        monkeypatch.setenv(provided, "path")
    monkeypatch.setattr(cabe, "import_module", lambda name: ModuleType(name))
    with pytest.raises(
        pp.ConfigurationError, match=r"CABE_CERTIFICATE_FILE.*CABE_KEY_FILE"
    ):
        async with cabe._service({"url": "https://keys/ckap"}):
            pytest.fail("missing credentials accepted")
