"""Key/secret provider indirection (KMS-ready secret sourcing).

Production secrets should not live as bare literals in the app environment or
image. This resolver lets any secret setting be sourced from an external manager
without adding SDK dependencies, by interpreting a small scheme prefix:

    literal (no scheme)   -> the value itself (dev/demo; backward compatible)
    literal:VALUE         -> the value after the prefix (escape hatch)
    env:OTHER_VAR         -> read another environment variable
    file:/run/secrets/x   -> read a mounted secret file (Docker/K8s secret)
    command:<shell>       -> run a command and use its stdout (Vault / AWS KMS /
                             GCP Secret Manager CLIs, e.g.
                             "command:aws kms decrypt --ciphertext-blob ... --output text")

So a KMS-managed key flows in via `file:` (a CSI-driver-mounted secret) or
`command:` (a fetch/decrypt CLI) — the raw key never sits in the deployment env.

Resolution is cached (secrets are stable for a process lifetime); rotating a
file-/command-sourced secret takes effect on restart. Provider errors are raised
loudly (a misconfigured production key should fail fast) but never include the
secret value in the message.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=256)
def resolve_secret(spec: str | None) -> str:
    """Resolve a secret spec to its literal value. Empty/None -> ""."""
    if not spec:
        return ""
    if spec.startswith("literal:"):
        return spec[len("literal:"):]
    if spec.startswith("env:"):
        return os.getenv(spec[len("env:"):], "").strip()
    if spec.startswith("file:"):
        path = Path(spec[len("file:"):])
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Could not read secret file '{path}': {exc.strerror}") from None
    if spec.startswith("command:"):
        cmd = spec[len("command:"):]
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, check=True, timeout=30
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Secret command failed (exit {exc.returncode}).") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError("Secret command timed out.") from None
        return result.stdout.strip()
    # No recognized scheme: treat as a literal value (backward compatible).
    return spec


def resolve_secrets(specs) -> tuple[str, ...]:
    """Resolve a sequence of specs, dropping any that resolve empty."""
    return tuple(s for s in (resolve_secret(spec) for spec in specs) if s)
