"""Permission-tier primitives shared by sessions and the M2 execution path."""

from __future__ import annotations

from enum import IntEnum


class PermissionTier(IntEnum):
    """Increasing capabilities for a human advisory session."""

    INFO = 0
    ADVISE = 1
    PROPOSE = 2
    EXECUTE = 3

