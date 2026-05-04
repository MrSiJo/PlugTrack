"""Tests for password hashing + Fernet helpers."""
from __future__ import annotations

import pytest


def test_password_hash_and_verify():
    from plugtrack.security.crypto import hash_password, verify_password

    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False


def test_password_verify_never_raises_on_garbage():
    from plugtrack.security.crypto import verify_password

    assert verify_password("anything", "not-an-argon2-hash") is False
    assert verify_password("", "") is False


def test_fernet_round_trip():
    from plugtrack.security.crypto import decrypt_secret, encrypt_secret

    secret = "x" * 48
    token = encrypt_secret("hello cupra", secret)
    assert token != "hello cupra"
    assert decrypt_secret(token, secret) == "hello cupra"


def test_fernet_rejects_empty_app_secret():
    from plugtrack.security.crypto import fernet_from_secret

    with pytest.raises(ValueError):
        fernet_from_secret("")
