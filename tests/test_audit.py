from wealth_advisor.audit import AuditLogger, verify_audit_log


def test_audit_chain_verifies_and_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path)
    logger.append("first", {"value": 1})
    logger.append("second", {"value": 2})
    assert verify_audit_log(path) == (True, "audit chain verified")
    content = path.read_text(encoding="utf-8").replace('"value":2', '"value":3')
    path.write_text(content, encoding="utf-8")
    valid, reason = verify_audit_log(path)
    assert not valid
    assert "hash mismatch" in reason

