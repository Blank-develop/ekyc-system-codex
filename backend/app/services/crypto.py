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

import json
from functools import lru_cache

from app.core.config import get_settings

PREFIX = "enc:v1:"


class TemplateCipher:
    def __init__(self, key: str) -> None:
        self._fernet = None
        if key:
            from cryptography.fernet import Fernet

            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

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
