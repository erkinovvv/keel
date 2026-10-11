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



def test_interleaved_sessions_keep_one_valid_chain(tmp_path):
    import threading

    from wealth_advisor.audit import AuditLogger, verify_audit_log

    path = tmp_path / "shared.jsonl"
    first, second = AuditLogger(path, session_id="s1"), AuditLogger(path, session_id="s2")
    first.append("a1"); second.append("b1"); first.append("a2")
    loggers = [AuditLogger(path, session_id=f"t{i}") for i in range(8)]
    threads = [threading.Thread(target=lambda lg=lg: [lg.append("x", {"i": k}) for k in range(25)]) for lg in loggers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert verify_audit_log(path) == (True, "audit chain verified")
    assert sum(1 for line in path.read_text().splitlines() if line.strip()) == 3 + 8 * 25
