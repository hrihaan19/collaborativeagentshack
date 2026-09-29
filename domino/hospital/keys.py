"""One Ed25519 key per hospital. Lives only in the hospital state dir."""
from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def load_or_create(state_dir: Path) -> Ed25519PrivateKey:
    p = state_dir / "hospital_ed25519.key"
    if p.exists():
        return serialization.load_pem_private_key(p.read_bytes(), password=None)  # type: ignore[return-value]
    key = Ed25519PrivateKey.generate()
    state_dir.mkdir(parents=True, exist_ok=True)
    p.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def sign_hex(key: Ed25519PrivateKey, plan_hash: str) -> str:
    return key.sign(plan_hash.encode("ascii")).hex()


def verify_hex(public_key_hex: str, plan_hash: str, signature_hex: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(bytes.fromhex(signature_hex), plan_hash.encode("ascii"))
        return True
    except Exception:  # noqa: BLE001 - any failure is "not verified"
        return False
