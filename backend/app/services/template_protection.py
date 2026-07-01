"""Cancelable / renewable biometric templates (ISO/IEC 24745).

Encryption at rest protects the template from a database read, but a decrypted
template is still the raw biometric. A *protected* template transforms the
embedding so the raw biometric is never present even in memory-after-decrypt, and
so templates can be **revoked and renewed** by changing the key (biometric
template protection, "cancelable biometrics").

We use a **key-derived orthonormal projection** Q (a rotation/reflection of the
embedding space). Because SFace embeddings are unit vectors and matching is a dot
product, an orthonormal transform preserves the score **exactly**:

    (Q·a) · (Q·b) = a · (QᵀQ) · b = a · b        (QᵀQ = I)

So accuracy is unchanged. The same key transforms both stored templates and the
live probe at match time, so comparison happens entirely in the protected space.

Properties (ISO 24745):
- **Renewability / revocability:** re-key → a new, unrelated template space; old
  templates no longer match (they are revoked). Re-enrollment is required after a
  re-key — this is the intended "cancel" behavior.
- **Unlinkability:** templates protected under different keys are not comparable,
  so the same person's templates in two systems can't be cross-linked.
- **Accuracy preserved:** exact score preservation (see identity above).

Honest scope: an orthonormal transform is invertible *with the key*, so this is a
keyed, renewable protection layered on top of encryption at rest — not a one-way
(fully irreversible) transform, which would trade away matching accuracy. Full
irreversibility (e.g. a lossy/one-way scheme) is future work.

Unset key -> no-op (returns the template unchanged) so dev/demo keep working.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from app.core.config import get_settings
from app.services.key_provider import resolve_secret


class TemplateProtector:
    def __init__(self, key: str) -> None:
        self._key = key or ""
        self._matrices: dict[int, object] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def _matrix(self, dim: int):
        cached = self._matrices.get(dim)
        if cached is not None:
            return cached
        import numpy as np

        # Deterministic Haar-distributed orthonormal matrix seeded from key + dim.
        seed = int.from_bytes(
            hashlib.sha256(f"{self._key}|{dim}".encode()).digest()[:8], "big"
        )
        rng = np.random.default_rng(seed)
        q, r = np.linalg.qr(rng.standard_normal((dim, dim)))
        # Fix column signs from R's diagonal so Q is unique/deterministic.
        q = q * np.sign(np.diag(r))
        self._matrices[dim] = q
        return q

    def protect(self, template: list[float]) -> list[float]:
        """Transform an embedding into the protected space (no-op when disabled)."""
        if not self._key or not template:
            return template
        import numpy as np

        vec = np.asarray(template, dtype=np.float64)
        return (self._matrix(len(template)) @ vec).tolist()


@lru_cache
def get_template_protector() -> TemplateProtector:
    return TemplateProtector(resolve_secret(get_settings().template_protection_key))
