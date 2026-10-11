"""Anchor the audit chain on a public blockchain (Ethereum Sepolia testnet).

The audit log is hash-chained, so its latest record hash commits to every record before it.
Anchoring that one hash in a transaction's data field gives anyone an independent, timestamped
proof that the log has not been rewritten since: recompute the chain, compare with the chain.

Payload (data field, 40 bytes): b"WA01" | 32-byte head hash | 4-byte big-endian record count.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAGIC = b"WA01"
SEPOLIA_CHAIN_ID = 11155111
DEFAULT_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
EXPLORER_TX = "https://sepolia.etherscan.io/tx/"


@dataclass(frozen=True)
class AnchorReceipt:
    tx_hash: str | None
    head_hash: str
    record_count: int
    payload_hex: str
    explorer_url: str | None
    sent: bool
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def head_of(path: str | Path, count: int | None = None) -> tuple[str, int]:
    """Return (hash of record #count, count) for the first `count` records (default: all)."""

    records = _records(Path(path))
    if not records:
        raise ValueError("audit log is empty; nothing to anchor")
    count = len(records) if count is None else count
    if not 1 <= count <= len(records):
        raise ValueError(f"audit log has {len(records)} records, cannot use the first {count}")
    return records[count - 1]["hash"], count


def encode_payload(head_hash: str, count: int) -> bytes:
    return MAGIC + bytes.fromhex(head_hash) + count.to_bytes(4, "big")


def decode_payload(data: bytes) -> tuple[str, int]:
    if len(data) != 40 or not data.startswith(MAGIC):
        raise ValueError("transaction data is not a Wealth Advisor anchor")
    return data[4:36].hex(), int.from_bytes(data[36:40], "big")


def _web3(rpc_url: str | None = None):
    from web3 import Web3

    return Web3(Web3.HTTPProvider(rpc_url or os.getenv("SEPOLIA_RPC_URL", DEFAULT_RPC), request_kwargs={"timeout": 20}))


def anchor_audit_log(path: str | Path, private_key: str | None = None, rpc_url: str | None = None, dry_run: bool = False) -> AnchorReceipt:
    """Send a zero-value self-transaction carrying the audit head hash. Falls back to a dry run without a key."""

    head, count = head_of(path)
    payload = encode_payload(head, count)
    key = private_key or os.getenv("SEPOLIA_PRIVATE_KEY")
    if dry_run or not key:
        return AnchorReceipt(None, head, count, payload.hex(), None, False, "dry run: no SEPOLIA_PRIVATE_KEY configured" if not key else "dry run")
    w3 = _web3(rpc_url)
    account = w3.eth.account.from_key(key)
    if w3.eth.get_balance(account.address) == 0:
        return AnchorReceipt(None, head, count, payload.hex(), None, False, f"wallet {account.address} has no Sepolia ETH; use a faucet")
    tx: dict[str, Any] = {
        "chainId": SEPOLIA_CHAIN_ID,
        "from": account.address,
        "to": account.address,
        "value": 0,
        "data": payload,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
    }
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    latest = w3.eth.get_block("latest")
    tip = w3.to_wei(1, "gwei")
    tx["maxPriorityFeePerGas"] = tip
    tx["maxFeePerGas"] = int(latest["baseFeePerGas"] * 2 + tip)
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = w3.eth.send_raw_transaction(raw).hex()
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    return AnchorReceipt(tx_hash, head, count, payload.hex(), EXPLORER_TX + tx_hash, True, "sent")


def verify_anchor(tx_hash: str, path: str | Path, rpc_url: str | None = None) -> dict[str, Any]:
    """Fetch an anchor transaction and check it against the local audit chain."""

    from wealth_advisor.audit import verify_audit_log

    w3 = _web3(rpc_url)
    tx = w3.eth.get_transaction(tx_hash)
    data = bytes(tx["input"])
    anchored_head, count = decode_payload(data)
    chain_ok, reason = verify_audit_log(path)
    local_head, _ = head_of(path, count)
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    block = w3.eth.get_block(receipt["blockNumber"])
    return {
        "tx_hash": tx_hash,
        "block": receipt["blockNumber"],
        "block_time": block["timestamp"],
        "anchored_head": anchored_head,
        "local_head": local_head,
        "record_count": count,
        "chain_valid": chain_ok,
        "chain_reason": reason,
        "matches": chain_ok and anchored_head == local_head,
        "explorer_url": EXPLORER_TX + tx_hash,
    }
