from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.services import auth
from app.services.crypto import TemplateCipher
from app.services.key_provider import resolve_secret, resolve_secrets


def setup_function() -> None:
    resolve_secret.cache_clear()  # avoid cross-test cache poisoning on env:/file:


# --- Provider resolution ------------------------------------------------------

def test_bare_literal_and_empty() -> None:
    assert resolve_secret("plain-value") == "plain-value"
    assert resolve_secret("") == ""
    assert resolve_secret(None) == ""


def test_literal_prefix_escape_hatch() -> None:
    assert resolve_secret("literal:file:not-a-path") == "file:not-a-path"


def test_env_provider(monkeypatch) -> None:
    monkeypatch.setenv("KP_TEST_SECRET", "  from-env  ")
    assert resolve_secret("env:KP_TEST_SECRET") == "from-env"


def test_file_provider(tmp_path) -> None:
    secret_file = tmp_path / "secret.key"
    secret_file.write_text("s3cret-from-file\n")
    assert resolve_secret(f"file:{secret_file}") == "s3cret-from-file"


def test_file_provider_missing_raises() -> None:
    with pytest.raises(RuntimeError):
        resolve_secret("file:/nonexistent/path/to/secret")


def test_command_provider() -> None:
    assert resolve_secret("command:printf 'from-cmd'") == "from-cmd"


def test_command_provider_failure_raises() -> None:
    with pytest.raises(RuntimeError):
        resolve_secret("command:exit 3")


def test_resolve_secrets_drops_empty(tmp_path) -> None:
    f = tmp_path / "k"
    f.write_text("k1")
    assert resolve_secrets([f"file:{f}", "", "literal:k2"]) == ("k1", "k2")


# --- Encryption key rotation (MultiFernet) ------------------------------------

def test_encryption_key_rotation() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    enc_old = TemplateCipher(old).encrypt_template([0.1, 0.2])

    # During rotation [new (primary), old (retired)] still decrypts old data...
    assert TemplateCipher([new, old]).decrypt_template(enc_old) == [0.1, 0.2]
    # ...but the retired key alone being gone means only-new cannot read old data.
    assert TemplateCipher([new]).decrypt_template(enc_old) is None
    # New data is encrypted under the primary (new) key.
    enc_new = TemplateCipher([new, old]).encrypt_template([0.3])
    assert TemplateCipher([new]).decrypt_template(enc_new) == [0.3]


# --- JWT secret rotation ------------------------------------------------------

def test_jwt_secret_rotation() -> None:
    token = auth.create_access_token("old-secret", "u1", "admin", 60)

    # Verify set [new, old] still accepts a token signed with the retired secret.
    assert auth.decode_token(["new-secret", "old-secret"], token)["sub"] == "u1"
    # Only the new secret -> the old token no longer verifies.
    assert auth.decode_token(["new-secret"], token) is None
    # Backward compatible: a single string still works.
    assert auth.decode_token("old-secret", token)["role"] == "admin"
