"""Encryption-at-rest for biometric templates.

The face template (the biometric embedding) is the most sensitive stored value.
When LALIGENCE_ENCRYPTION_KEY is set, templates are encrypted with authenticated
symmetric encryption (Fernet / AES-128-CBC + HMAC) before they reach the
database, and decrypted only in memory for matching.

No key configured -> no-op (plaintext), so local/dev/demo keep working. Existing
plaintext rows stay readable (backward compatible), and the encrypted form is a
prefixed string so the two are distinguishable.

Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import hashlib
import hmac
import json
from functools import lru_cache

from app.core.config import get_settings

PREFIX = "enc:v1:"


class TemplateCipher:
    def __init__(self, key: str) -> None:
        self._fernet = None
        self._index_key = b""
        if key:
            from cryptography.fernet import Fernet

            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
            # Separate derived key for blind indexes (don't reuse the cipher key directly).
            self._index_key = hashlib.sha256(key.encode() + b"|blind-index").digest()

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt_json(self, obj) -> str | None:
        if self._fernet is None:
            return None
        return PREFIX + self._fernet.encrypt(json.dumps(obj).encode()).decode()

    def decrypt_json(self, stored) -> dict | None:
        if not isinstance(stored, str) or not stored.startswith(PREFIX) or self._fernet is None:
            return None
        try:
            return json.loads(self._fernet.decrypt(stored[len(PREFIX):].encode()).decode())
        except Exception:
            return None

    def blind_index(self, value) -> str | None:
        """Deterministic keyed hash for equality lookups on encrypted fields,
        without revealing the value (e.g. passport-number uniqueness)."""
        if value is None or self._fernet is None:
            return None
        normalized = str(value).strip().upper().encode()
        return hmac.new(self._index_key, normalized, hashlib.sha256).hexdigest()

    def encrypt_template(self, template: list[float]) -> list[float] | str:
        floats = [float(v) for v in template]
        if self._fernet is None:
            return floats
        token = self._fernet.encrypt(json.dumps(floats).encode()).decode()
        return PREFIX + token

    def decrypt_template(self, stored) -> list[float] | None:
        # Already-plaintext (legacy rows or no-key mode): a JSON list.
        if isinstance(stored, list):
            return stored
        if isinstance(stored, str) and stored.startswith(PREFIX):
            if self._fernet is None:
                return None  # encrypted but no key available -> unusable
            try:
                data = self._fernet.decrypt(stored[len(PREFIX):].encode())
                return json.loads(data.decode())
            except Exception:
                return None  # wrong key / corrupt -> fail safe
        return None


@lru_cache
def get_template_cipher() -> TemplateCipher:
    return TemplateCipher(get_settings().encryption_key)
