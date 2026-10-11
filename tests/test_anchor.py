import pytest

from wealth_advisor.anchor import anchor_audit_log, decode_payload, encode_payload, head_of
from wealth_advisor.audit import AuditLogger


def _log(tmp_path, n=3):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path)
    for index in range(n):
        logger.append("event", {"index": index})
    return path


def test_payload_round_trip():
    head = "ab" * 32
    data = encode_payload(head, 42)
    assert len(data) == 40
    assert decode_payload(data) == (head, 42)


def test_foreign_payload_is_rejected():
    with pytest.raises(ValueError):
        decode_payload(b"\x00" * 40)


def test_head_commits_to_the_requested_prefix(tmp_path):
    path = _log(tmp_path, 5)
    full_head, count = head_of(path)
    prefix_head, prefix_count = head_of(path, 3)
    assert count == 5 and prefix_count == 3 and full_head != prefix_head


def test_dry_run_without_key_never_sends(tmp_path, monkeypatch):
    monkeypatch.delenv("SEPOLIA_PRIVATE_KEY", raising=False)
    receipt = anchor_audit_log(_log(tmp_path))
    assert not receipt.sent and receipt.tx_hash is None
    assert decode_payload(bytes.fromhex(receipt.payload_hex)) == head_of(tmp_path / "audit.jsonl")


def test_empty_log_cannot_be_anchored(tmp_path):
    with pytest.raises(ValueError):
        head_of(tmp_path / "missing.jsonl")
