"""Anchor the audit chain on a blockchain: WeBank's FISCO BCOS, or the Ethereum Sepolia testnet.

The audit log is hash-chained, so its latest record hash commits to every record before it.
Writing that one hash on a chain gives anyone an independent, timestamped proof that the log has
not been rewritten since: recompute the chain locally and compare with what the chain holds.

Networks (ANCHOR_NETWORK):
- ``fisco``: a FISCO BCOS 3.x consortium chain (the open-source chain led by WeBank), through its
  Web3-compatible RPC. The head is written by calling ``AuditAnchor.anchor(head, count)``
  (contracts/AuditAnchor.sol); the contract is deployed on first use and its address remembered.
- ``sepolia`` (default): a zero-value self-transaction whose 40-byte data field is
  b"WA01" | 32-byte head hash | 4-byte big-endian record count.
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
FISCO_DEFAULT_RPC = "http://127.0.0.1:8545"
FISCO_HOME = Path(os.getenv("FISCO_HOME", Path.home() / ".wealth-advisor" / "fisco"))
CONTRACT = Path(__file__).parent / "data" / "audit_anchor_contract.json"


@dataclass(frozen=True)
class AnchorReceipt:
    tx_hash: str | None
    head_hash: str
    record_count: int
    payload_hex: str
    explorer_url: str | None
    sent: bool
    note: str
    network: str = "sepolia"
    block: int | None = None

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
        raise ValueError("transaction data is not a Keel audit anchor")
    return data[4:36].hex(), int.from_bytes(data[36:40], "big")


def network() -> str:
    return "fisco" if os.getenv("ANCHOR_NETWORK", "sepolia").lower() == "fisco" else "sepolia"


def _web3(rpc_url: str | None = None, net: str | None = None):
    from web3 import Web3

    net = net or network()
    default = os.getenv("FISCO_RPC_URL", FISCO_DEFAULT_RPC) if net == "fisco" else os.getenv("SEPOLIA_RPC_URL", DEFAULT_RPC)
    return Web3(Web3.HTTPProvider(rpc_url or default, request_kwargs={"timeout": 20}))


def _hex(tx_hash: Any) -> str:
    value = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
    return value if value.startswith("0x") else "0x" + value


# ---------------------------------------------------------------- FISCO BCOS


def _fisco_key() -> str:
    """Account key for the consortium chain: env FISCO_PRIVATE_KEY, else a key kept in FISCO_HOME."""

    if key := os.getenv("FISCO_PRIVATE_KEY"):
        return key
    from eth_account import Account

    path = FISCO_HOME / "anchor_account.json"
    if path.exists():
        return json.loads(path.read_text())["private_key"]
    account = Account.create()
    FISCO_HOME.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"address": account.address, "private_key": account.key.hex()}))
    path.chmod(0o600)
    return account.key.hex()


def _send(w3, account, tx: dict[str, Any]) -> Any:
    tx = {**tx, "chainId": w3.eth.chain_id, "from": account.address, "nonce": w3.eth.get_transaction_count(account.address), "gasPrice": 0}
    tx.setdefault("gas", 3_000_000)
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw), timeout=30)
    if receipt["status"] != 1:
        raise RuntimeError(f"FISCO BCOS transaction failed in block {receipt['blockNumber']}")
    return receipt


def _anchor_contract(w3, account):
    """Return the deployed AuditAnchor contract, deploying it once if needed."""

    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    path = FISCO_HOME / "anchor_contract.json"
    chain_id = w3.eth.chain_id
    if path.exists():
        saved = json.loads(path.read_text())
        if saved.get("chain_id") == chain_id and len(w3.eth.get_code(saved["address"])) > 0:
            return w3.eth.contract(address=saved["address"], abi=spec["abi"])
    receipt = _send(w3, account, {"data": spec["bytecode"], "gas": 3_000_000})
    address = receipt["contractAddress"]
    FISCO_HOME.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"address": address, "chain_id": chain_id, "deployed_in_block": receipt["blockNumber"]}))
    return w3.eth.contract(address=address, abi=spec["abi"])


def _anchor_fisco(head: str, count: int, payload: bytes, rpc_url: str | None) -> AnchorReceipt:
    w3 = _web3(rpc_url, "fisco")
    if not w3.is_connected():
        return AnchorReceipt(None, head, count, payload.hex(), None, False, "FISCO BCOS node is not running (scripts/fisco_chain.sh start)", "fisco")
    account = w3.eth.account.from_key(_fisco_key())
    contract = _anchor_contract(w3, account)
    call = contract.functions.anchor(bytes.fromhex(head), count).build_transaction({"from": account.address, "gas": 200_000, "gasPrice": 0, "nonce": 0, "chainId": w3.eth.chain_id})
    receipt = _send(w3, account, {"to": contract.address, "data": call["data"], "gas": 200_000})
    return AnchorReceipt(_hex(receipt["transactionHash"]), head, count, payload.hex(), None, True, f"FISCO BCOS contract {contract.address}", "fisco", receipt["blockNumber"])


# ---------------------------------------------------------------- entry points


def anchor_audit_log(path: str | Path, private_key: str | None = None, rpc_url: str | None = None, dry_run: bool = False) -> AnchorReceipt:
    """Anchor the audit head on the configured network. Sepolia falls back to a dry run without a key."""

    head, count = head_of(path)
    payload = encode_payload(head, count)
    if network() == "fisco" and not dry_run:
        return _anchor_fisco(head, count, payload, rpc_url)
    key = private_key or os.getenv("SEPOLIA_PRIVATE_KEY")
    if dry_run or not key:
        return AnchorReceipt(None, head, count, payload.hex(), None, False, "dry run: no SEPOLIA_PRIVATE_KEY configured" if not key else "dry run")
    w3 = _web3(rpc_url, "sepolia")
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
    tx_hash = _hex(w3.eth.send_raw_transaction(raw))
    return AnchorReceipt(tx_hash, head, count, payload.hex(), EXPLORER_TX + tx_hash, True, "sent")


def verify_anchor(tx_hash: str, path: str | Path, rpc_url: str | None = None) -> dict[str, Any]:
    """Fetch an anchor transaction and check it against the local audit chain."""

    from wealth_advisor.audit import verify_audit_log

    net = network()
    w3 = _web3(rpc_url, net)
    tx = w3.eth.get_transaction(tx_hash)
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    if net == "fisco":
        spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract = w3.eth.contract(address=tx["to"], abi=spec["abi"])
        _, args = contract.decode_function_input(tx["input"])
        anchored_head, count = args["head"].hex().removeprefix("0x"), int(args["recordCount"])
        on_chain_block = contract.functions.anchoredAtBlock(args["head"]).call()
        status_ok = receipt["status"] == 1 and on_chain_block > 0
    else:
        anchored_head, count = decode_payload(bytes(tx["input"]))
        status_ok = True
    chain_ok, reason = verify_audit_log(path)
    local_head, _ = head_of(path, count)
    block = w3.eth.get_block(receipt["blockNumber"])
    return {
        "network": net,
        "tx_hash": tx_hash,
        "block": receipt["blockNumber"],
        "block_time": block["timestamp"],
        "anchored_head": anchored_head,
        "local_head": local_head,
        "record_count": count,
        "chain_valid": chain_ok,
        "chain_reason": reason,
        "matches": status_ok and chain_ok and anchored_head == local_head,
        "explorer_url": EXPLORER_TX + tx_hash if net == "sepolia" else None,
    }
