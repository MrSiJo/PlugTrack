"""Password hashing (argon2id) + symmetric secret encryption (Fernet).

`fernet_from_secret` derives a 32-byte Fernet key by SHA-256-hashing the
APP_SECRET_KEY and base64-url-encoding the digest. Operators only need to
set APP_SECRET_KEY.

⚠ Rotation is destructive and irreversible without care: APP_SECRET_KEY is
also the session-cookie signer, and there is no key versioning. Changing it
orphans every value encrypted under the old key (stored settings secrets +
car VINs will fail to decrypt) and invalidates all sessions. Decrypt/clear
those values under the old key before rotating, then re-enter them. See the
rotation note in `.env.example`.
"""
from __future__ import annotations

import base64
import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet


_HASHER = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=2)


def hash_password(plain: str) -> str:
    return _HASHER.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return _HASHER.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def fernet_from_secret(app_secret: str) -> Fernet:
    if not app_secret:
        raise ValueError("APP_SECRET_KEY must be a non-empty string")
    digest = hashlib.sha256(app_secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plain: str, app_secret: str) -> str:
    return fernet_from_secret(app_secret).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, app_secret: str) -> str:
    return fernet_from_secret(app_secret).decrypt(token.encode("ascii")).decode("utf-8")
