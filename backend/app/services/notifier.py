"""Out-of-band notifications (enrollment codes + notification-of-proofing).

NIST 800-63A IAL2 requires (a) confirming a validated address/phone by sending an
enrollment code the applicant returns, and (b) notifying the applicant that a
proofing occurred. This module delivers those messages through a pluggable channel
so production can wire a real email/SMS provider without adding an SDK dependency:

    console (default)   -> log only (dev/demo; no external send)
    command:<shell>     -> run a command with the message on env vars, e.g.
                           "command:sendmail-cli --to \"$NOTIFY_TO\" --body \"$NOTIFY_BODY\""
                           (NOTIFY_CHANNEL / NOTIFY_TO / NOTIFY_SUBJECT / NOTIFY_BODY)

Never logs the code at console level in a way that would leak it in shared logs
beyond what the operator opts into; the code itself is only in the body passed to
the configured provider.
"""

from __future__ import annotations

import logging
import os
import subprocess
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger("kyron.notifier")


class Notifier:
    def __init__(self, spec: str) -> None:
        self._spec = spec or "console"

    def send(self, channel: str, destination: str, subject: str, body: str) -> bool:
        """Deliver a message. Returns True on success. Never raises to the caller."""
        try:
            if self._spec.startswith("command:"):
                env = {
                    **os.environ,
                    "NOTIFY_CHANNEL": channel,
                    "NOTIFY_TO": destination,
                    "NOTIFY_SUBJECT": subject,
                    "NOTIFY_BODY": body,
                }
                result = subprocess.run(
                    self._spec[len("command:"):], shell=True, env=env,
                    capture_output=True, text=True, timeout=30,
                )
                return result.returncode == 0
            # console / default: record that a message was sent, without the code.
            logger.info("notifier: %s message to %s (%s)", channel, _mask(destination), subject)
            return True
        except Exception:
            return False


def _mask(destination: str) -> str:
    d = (destination or "").strip()
    if "@" in d:
        name, _, domain = d.partition("@")
        head = name[0] if name else ""
        return f"{head}***@{domain}"
    if len(d) > 4:
        return f"***{d[-4:]}"
    return "***"


mask_destination = _mask


@lru_cache
def get_notifier() -> Notifier:
    return Notifier(get_settings().notifier)
