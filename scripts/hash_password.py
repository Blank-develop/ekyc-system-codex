#!/usr/bin/env python3
"""Generate a LALIGENCE_AUTH_USERS entry (PBKDF2 password hash) for JWT auth.

Usage:
    python scripts/hash_password.py <username> <role> [password]

If the password is omitted you are prompted for it (not echoed). Prints a single
"username:pbkdf2_hash:role" entry — add it (comma-separated) to LALIGENCE_AUTH_USERS,
and set LALIGENCE_JWT_SECRET (e.g. `openssl rand -hex 32`) to enable auth.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.auth import hash_password  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    username, role = sys.argv[1], sys.argv[2]
    password = sys.argv[3] if len(sys.argv) > 3 else getpass.getpass("Password: ")
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1
    print(f"{username}:{hash_password(password)}:{role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
