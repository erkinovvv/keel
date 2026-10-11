#!/usr/bin/env bash
# Local 4-node FISCO BCOS 3.x consortium chain (WeBank's open-source blockchain) for audit anchoring.
#
#   scripts/fisco_chain.sh setup    download the binary and generate 4 nodes (once)
#   scripts/fisco_chain.sh start    start the nodes; Web3 RPC on 127.0.0.1:8545 (chain id 20200)
#   scripts/fisco_chain.sh stop
#   scripts/fisco_chain.sh status
#
# Nodes live in ~/.wealth-advisor/fisco (override with FISCO_HOME); the FISCO start scripts do
# not support spaces in paths, so the chain is kept outside the repository.
set -euo pipefail

VERSION="v3.17.1"
HOME_DIR="${FISCO_HOME:-$HOME/.wealth-advisor/fisco}"
NODES="$HOME_DIR/nodes/127.0.0.1"

asset() {
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) echo "fisco-bcos-macOS-arm.tar.gz" ;;
    Darwin-x86_64) echo "fisco-bcos-macOS-x86_64.tar.gz" ;;
    Linux-aarch64) echo "fisco-bcos-linux-aarch64.tar.gz" ;;
    *) echo "fisco-bcos-linux-x86_64.tar.gz" ;;
  esac
}

setup() {
  mkdir -p "$HOME_DIR" && cd "$HOME_DIR"
  local base="https://github.com/FISCO-BCOS/FISCO-BCOS/releases/download/$VERSION"
  [ -f build_chain.sh ] || curl -fsSL -o build_chain.sh "$base/build_chain.sh"
  if [ ! -x fisco-bcos ]; then
    curl -fsSL -o fisco.tar.gz "$base/$(asset)"
    tar -xzf fisco.tar.gz && rm fisco.tar.gz
  fi
  if [ ! -d "$NODES" ]; then
    bash build_chain.sh -l 127.0.0.1:4 -p 30300,20200 -e ./fisco-bcos -o nodes
    # Enable the Web3-compatible JSON-RPC on node0 only, bound to localhost.
    python3 - "$NODES/node0/config.ini" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path).read()
text = re.sub(r"(\[web3_rpc\]\n\s+enable=)false(\n\s+listen_ip=)0\.0\.0\.0", r"\1true\g<2>127.0.0.1", text)
open(path, "w").write(text)
PY
  fi
  echo "FISCO BCOS $VERSION ready in $HOME_DIR"
}

case "${1:-status}" in
  setup) setup ;;
  start) [ -d "$NODES" ] || setup; bash "$NODES/start_all.sh" ;;
  stop) bash "$NODES/stop_all.sh" ;;
  status)
    curl -s -m 5 -X POST http://127.0.0.1:8545 -H 'content-type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
      && echo || echo "FISCO BCOS is not running (scripts/fisco_chain.sh start)"
    ;;
  *) echo "usage: $0 setup|start|stop|status" >&2; exit 2 ;;
esac
