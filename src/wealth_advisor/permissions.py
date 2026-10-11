"""Permission tiers and one-time human confirmation tokens."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum


class PermissionTier(IntEnum):
    """Increasing capabilities for a human advisory session."""

    INFO = 0
    ADVISE = 1
    PROPOSE = 2
    EXECUTE = 3


class PermissionDenied(PermissionError):
    """Raised when a session attempts an operation above its configured tier."""


def require_tier(current: int, required: int) -> None:
    if current < required:
        raise PermissionDenied(f"permission tier {current} cannot perform tier {required} operation")


@dataclass(frozen=True)
class _TokenRecord:
    order_id: str
    token_hash: str
    summary_hash: str
    expires_at: datetime


class ConfirmationTokenStore:
    """Issue and consume opaque tokens in application memory, never in model state."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._records: dict[str, _TokenRecord] = {}

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def issue(self, order_id: str, order_summary: str) -> str:
        token = secrets.token_urlsafe(24)
        self._records[order_id] = _TokenRecord(
            order_id=order_id,
            token_hash=self._hash(token),
            summary_hash=self._hash(order_summary),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
        )
        return token

    def consume(self, order_id: str, token: str, order_summary: str) -> bool:
        record = self._records.pop(order_id, None)
        if record is None or record.expires_at < datetime.now(timezone.utc):
            return False
        return secrets.compare_digest(record.token_hash, self._hash(token)) and secrets.compare_digest(record.summary_hash, self._hash(order_summary))
