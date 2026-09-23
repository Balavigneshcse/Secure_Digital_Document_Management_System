"""Generates a self-signed TLS certificate for local / demo deployments:

    python -m app.selfsigned /certs localhost 127.0.0.1

Writes tls.crt and tls.key (ECDSA P-256) if they don't already exist. Replace them with a certificate from your
organisation's CA for any real deployment - a self-signed certificate makes browsers warn and proves nothing to clients.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import pathlib
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def generate(out_dir: pathlib.Path, names: list[str]) -> bool:
    crt, key = out_dir / "tls.crt", out_dir / "tls.key"
    if crt.exists() and key.exists():
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    private = ec.generate_private_key(ec.SECP256R1())
    sans: list[x509.GeneralName] = []
    for n in names:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            sans.append(x509.DNSName(n))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0]), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SDMS (self-signed, demo)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(private.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(private, hashes.SHA256())
    )
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key.chmod(0o600)  # the web server's master process runs as root and reads it; nobody else needs to
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return True


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "certs")
    hosts = sys.argv[2:] or ["localhost", "127.0.0.1"]
    print("generated" if generate(target, hosts) else "certificate already present", "->", target)
