"""Byte-stream CABE transforms backed by the optional ``cabe`` extra.

Encryption nodes each own one PyCABE client and its lease cache. Service settings
are captured at startup; encapsulation attributes are read for each message.
Printer inspects envelope headers locally, without a client or decryption.
Importing this module or declaring graphs does not import PyCABE or perform I/O.
"""

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from importlib import import_module
from itertools import chain
from typing import Protocol, cast

from ._exceptions import ConfigurationError
from ._node import node_type
from ._properties import Property
from .nodes import Transform

__all__ = ["Decapsulator", "Encapsulator", "Printer"]


class _Message(Protocol):
    @property
    def payload(self) -> bytes: ...


class _Headers(Protocol):
    @property
    def protected(self) -> Mapping[int | str, object]: ...

    @property
    def unprotected(self) -> Mapping[int | str, object]: ...


class _Envelope(Protocol):
    @property
    def lease_ref(self) -> bytes: ...

    @property
    def headers(self) -> _Headers: ...

    @property
    def attributes(self) -> Mapping[str, object]: ...

    def encode(self) -> bytes: ...


class _EnvelopeFactory(Protocol):
    def decode(self, encoded: bytes, *, wire_limit: int | None = None) -> _Envelope: ...


class _Client(Protocol):
    async def encapsulate(self, message: _Message) -> _Envelope: ...

    async def decapsulate(self, envelope: _Envelope) -> _Message: ...


class _API(Protocol):
    def Client(
        self, base_url: str, **options: object
    ) -> AbstractAsyncContextManager[_Client]: ...

    def Message(self, payload: bytes, attributes: dict[str, object]) -> _Message: ...

    @property
    def Envelope(self) -> _EnvelopeFactory: ...


@dataclass
class _Codec:
    api: _API
    client: _Client
    wire_limit: int | None = None

    async def encapsulate(self, payload: bytes, attrs: dict[str, object]) -> bytes:
        message = self.api.Message(payload, attrs)
        envelope = await self.client.encapsulate(message)
        return envelope.encode()

    async def decapsulate(self, payload: bytes) -> bytes:
        envelope = self.api.Envelope.decode(payload, wire_limit=self.wire_limit)
        message = await self.client.decapsulate(envelope)
        return message.payload


def _load_api() -> _API:
    try:
        return cast(_API, import_module("cabe"))
    except ModuleNotFoundError as error:
        if error.name != "cabe":
            raise
        raise ImportError(
            "CABE nodes require optional dependencies: pip install 'Pyrophone[cabe]'"
        ) from error


@asynccontextmanager
async def _service(service: dict[str, object]) -> AsyncIterator[_Codec]:
    api = _load_api()
    tls_module = import_module("cabe.tls")
    options = dict(service)
    url = options.pop("url", None)
    tls = options.pop("tls", {})
    if not isinstance(url, str) or not url:
        raise ConfigurationError("service.url must be a nonempty CABE service URL")
    if not isinstance(tls, dict):
        raise ConfigurationError("service.tls must be a dictionary")
    tls = dict(tls)
    for field, variable in (
        ("cert_file", "CABE_CERTIFICATE_FILE"),
        ("key_file", "CABE_KEY_FILE"),
        ("ca_file", "CABE_CA_FILE"),
    ):
        if path := os.getenv(variable):
            tls.setdefault(field, path)
    if not tls.get("cert_file") or not tls.get("key_file"):
        raise ConfigurationError(
            "service.tls requires cert_file and key_file, or set "
            "CABE_CERTIFICATE_FILE and CABE_KEY_FILE"
        )
    async with api.Client(url, tls=tls_module.FileTLS(**tls), **options) as client:
        yield _Codec(api, client, cast(int | None, options.get("wire_limit")))


class _CABETransform(Transform[bytes, bytes]):
    service = Property[dict[str, object]](
        title="Key service",
        description=(
            "CABE service URL and optional PyCABE client settings. Missing TLS "
            "paths default from CABE_CERTIFICATE_FILE, CABE_KEY_FILE and "
            "CABE_CA_FILE when the node starts."
        ),
    )
    _codec: _Codec

    async def run(self) -> None:
        async with _service(self.service) as self._codec:
            await super().run()


@node_type
class Encapsulator(_CABETransform):
    """Encrypt each plaintext byte payload into one encoded CABE envelope."""

    attrs = Property[dict[str, object]](
        default={},
        title="Attributes",
        description="CABE attributes for each outgoing message, such as sensitivity.",
    )

    async def transform(self, value: bytes) -> bytes:
        return await self._codec.encapsulate(value, self.attrs)


@node_type
class Decapsulator(_CABETransform):
    """Authenticate and decrypt each CABE envelope, emitting only its payload.

    Envelope attributes and content type are not forwarded on the bytes port.
    Decode, authorization, and authentication errors fail the node; unauthenticated
    plaintext is never emitted.
    """

    async def transform(self, value: bytes) -> bytes:
        return await self._codec.decapsulate(value)


_HEADER_NAMES = {
    2: "critical",
    3: "content_type",
    4: "key_id",
    5: "iv",
    7: "counter_signature",
}


def _format_label(label: int | str) -> str:
    if isinstance(label, int):
        return _HEADER_NAMES.get(label, str(label))
    return label if label.isascii() and label.isidentifier() else json.dumps(label)


def _format_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bytes):
        return value.hex()
    return ascii(value)


def _format_envelope(envelope: _Envelope) -> str:
    attributes = ", ".join(
        f"{_format_label(name)}={_format_value(value)}"
        for name, value in sorted(envelope.attributes.items())
    )
    reference = envelope.lease_ref.hex()
    fields = [f"Attributes=({attributes})", f"LeaseRef={reference}"]
    headers = envelope.headers
    for label, value in chain(headers.protected.items(), headers.unprotected.items()):
        if label not in (1, 6, "CABE_AttributeSet", "CABE_LeaseRef"):
            fields.append(f"{_format_label(label)}={_format_value(value)}")
    return "CABE Envelope: " + ", ".join(fields)


@node_type
class Printer(Transform[bytes, bytes]):
    """Print CABE headers on one stdout line and forward the original bytes.

    Inspection decodes and validates the envelope format without contacting a
    key service. Headers remain unverified; this node does not authenticate or
    decrypt messages. Attributes appear first; lease references use full hex.
    Algorithm and partial IV are omitted; other headers follow.
    """

    async def transform(self, value: bytes) -> bytes:
        envelope = _load_api().Envelope.decode(value)
        print(_format_envelope(envelope), flush=True)
        return value
