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


def _fisco_running() -> bool:
    import urllib.request

    try:
        request = urllib.request.Request("http://127.0.0.1:8545", data=b'{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}', headers={"content-type": "application/json"})
        return b"result" in urllib.request.urlopen(request, timeout=2).read()
    except OSError:
        return False


@pytest.mark.skipif(not _fisco_running(), reason="local FISCO BCOS chain not running (scripts/fisco_chain.sh start)")
def test_fisco_bcos_anchor_round_trip_and_tamper_detection(tmp_path, monkeypatch):
    from wealth_advisor.anchor import verify_anchor

    monkeypatch.setenv("ANCHOR_NETWORK", "fisco")
    path = _log(tmp_path, 4)
    receipt = anchor_audit_log(path)
    assert receipt.sent and receipt.network == "fisco" and receipt.block
    assert verify_anchor(receipt.tx_hash, path)["matches"]
    lines = path.read_text().splitlines()
    lines[1] = lines[1].replace('"index":1', '"index":7')
    path.write_text("\n".join(lines) + "\n")
    assert not verify_anchor(receipt.tx_hash, path)["matches"]
