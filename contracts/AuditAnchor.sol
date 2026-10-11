// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// Anchors the head hash of the Wealth Advisor hash-chained audit log.
/// The head commits to every earlier record, so one anchor proves the whole prefix.
contract AuditAnchor {
    event Anchored(bytes32 indexed head, uint32 recordCount, address indexed by, uint256 timestamp);

    mapping(bytes32 => uint256) public anchoredAtBlock;

    function anchor(bytes32 head, uint32 recordCount) external {
        if (anchoredAtBlock[head] == 0) {
            anchoredAtBlock[head] = block.number;
        }
        emit Anchored(head, recordCount, msg.sender, block.timestamp);
    }
}
