#!/usr/bin/env python3
"""Create a private demo PKI once; existing credentials are preserved."""

import ipaddress
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

STATE = Path(__file__).resolve().parents[1] / ".cabe"


def main() -> None:
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    STATE.chmod(0o700)
    (STATE / "keys").mkdir(mode=0o700, exist_ok=True)
    names = (
        "ca.pem",
        "ca-key.pem",
        "server.pem",
        "server-key.pem",
        "client.pem",
        "client-key.pem",
    )
    existing = [name for name in names if (STATE / name).exists()]
    if len(existing) == len(names):
        return
    if existing:
        raise SystemExit(
            "Incomplete .cabe credentials; stop the demo and remove its PEM files before regenerating."
        )
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pyrophone demo CA")])

    def certificate(
        name: x509.Name, key: ec.EllipticCurvePrivateKey, *, ca: bool = False
    ) -> x509.CertificateBuilder:
        return (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(
                x509.BasicConstraints(ca=ca, path_length=None), critical=True
            )
        )

    def save(
        name: str, key: ec.EllipticCurvePrivateKey, cert: x509.Certificate
    ) -> None:
        (STATE / f"{name}-key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (STATE / f"{name}.pem").write_bytes(
            cert.public_bytes(serialization.Encoding.PEM)
        )

    save(
        "ca",
        ca_key,
        certificate(ca_name, ca_key, ca=True).sign(ca_key, hashes.SHA256()),
    )
    for name, sans, usage in (
        (
            "server",
            [
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
                x509.DNSName("khaled"),
            ],
            ExtendedKeyUsageOID.SERVER_AUTH,
        ),
        (
            "client",
            [x509.UniformResourceIdentifier("urn:pyrophone:demo")],
            ExtendedKeyUsageOID.CLIENT_AUTH,
        ),
    ):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        cert = (
            certificate(subject, key)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        save(name, key, cert)


if __name__ == "__main__":
    main()
