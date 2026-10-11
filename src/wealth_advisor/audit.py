"""Append-only, hash-chained audit records."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# One lock per log file shared by every logger in the process; fcntl.flock covers other processes.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _last_hash_on_disk(stream) -> str | None:
    """Hash of the last record in an open file, read from the end so large logs stay cheap."""

    stream.seek(0, os.SEEK_END)
    position = stream.tell()
    buffer = b""
    while position > 0:
        step = min(4096, position)
        position -= step
        stream.seek(position)
        buffer = stream.read(step) + buffer
        lines = [line for line in buffer.splitlines() if line.strip()]
        if len(lines) >= 2 or (lines and position == 0):
            return json.loads(lines[-1])["hash"]
    return None


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class AuditLogger:
    """Write tamper-evident JSONL records for model, tool, and flow events.

    Many sessions may share one file. Each append takes a per-file lock (threads) and an exclusive
    flock (processes), reads the true last hash from disk and only then writes, so interleaved
    sessions still form a single valid chain. ``session_id`` (a pseudonymous tag) is stored on every
    record so one session can be replayed from a shared log.
    """

    def __init__(self, path: str | Path, session_id: str | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id

    @property
    def _last_hash(self) -> str | None:  # kept for callers that read it
        if not self.path.exists():
            return None
        with self.path.open("rb") as stream:
            return _last_hash_on_disk(stream)

    def append(self, event: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        """Append a record whose hash commits to the previous record in the file."""

        with _lock_for(self.path), self.path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                record: dict[str, Any] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": event,
                    "details": details or {},
                    "prev_hash": _last_hash_on_disk(stream),
                }
                if self.session_id:
                    record["session"] = self.session_id
                record["hash"] = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
                stream.seek(0, os.SEEK_END)
                stream.write((_canonical(record) + "\n").encode("utf-8"))
                stream.flush()
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
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

