# Execution evidence

Generated 2026-10-11 15:11 UTC by `uv run python scripts/run_evidence.py` on the simulated brokerage account, real Chinese fund catalog, local FISCO BCOS 3.17 consortium chain.

| Scenario | What it shows | Result | Audit chain | FISCO BCOS anchor |
|---|---|---|---|---|
| [01-conservative-client](01-conservative-client/) | A cautious 66-year-old: profiling, allocation within an 8% loss limit, comparison, stress test, goal, signed disclosure, hold-to-confirm execution. | `{"class": 2, "executed": 2, "total": 200000.0}` | valid, 15 records | block 9, tx `0xa253c446ca14…`, verified True |
| [02-crash-rehearsal](02-crash-rehearsal/) | A self-declared aggressive investor sells during the 2008 replay; the class is lowered, the old portfolio is refused, a suitable one is rebuilt and executed. | `{"class_before": 5, "class_after": 3, "old_class_request_status": 403, "executed": 4, "total": 100000.0}` | valid, 20 records | block 10, tx `0xcb993c5e55b9…`, verified True |
| [03-controls](03-controls/) | Server-side controls: above-class request, trading before consent, forged and replayed confirmation tokens, PII masking. | `{"forged_token_executed": 0, "replayed_token_executed": 0, "redacted_message": "My [PASSPORT_REDACTED] and my card is [PHONE_REDACTED]"}` | valid, 15 records | block 11, tx `0xe9727ea8b524…`, verified True |

Files per scenario: `audit.jsonl` (hash-chained log; check with `uv run wealth-advisor --verify-audit` and `AUDIT_LOG=<file>`), `transcript.json` (every request and response), `summary.json` (outcome and final account state), `anchor.json` (FISCO BCOS transaction and verification), `advice_report.html` (client-facing record, its SHA-256 is in the audit log).
