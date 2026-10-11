"""Append-only, hash-chained audit records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class AuditLogger:
    """Write tamper-evident JSONL records for model, tool, and flow events."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str | None:
        if not self.path.exists():
            return None
        last: str | None = None
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def append(self, event: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        """Append a record whose hash commits to the previous record."""

        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": details or {},
            "prev_hash": self._last_hash,
        }
        record["hash"] = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(_canonical(record) + "\n")
        self._last_hash = record["hash"]
        return record


def verify_audit_log(path: str | Path) -> tuple[bool, str]:
    """Verify record hashes and links, returning a status and human-readable reason."""

    audit_path = Path(path)
    if not audit_path.exists():
        return True, "audit log does not exist"
    previous: str | None = None
    try:
        with audit_path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                saved_hash = record.pop("hash")
                if record.get("prev_hash") != previous:
                    return False, f"prev_hash mismatch at line {line_number}"
                calculated = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
                if saved_hash != calculated:
                    return False, f"hash mismatch at line {line_number}"
                previous = saved_hash
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        return False, f"invalid audit log: {exc}"
    return True, "audit chain verified"

