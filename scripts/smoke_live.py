"""Run a short live Groq journey when GROQ_API_KEY is configured."""

from __future__ import annotations

import json
import os
import sys

from wealth_advisor.config import Settings
from wealth_advisor.permissions import PermissionTier
from wealth_advisor.session import AdvisorSession


def main() -> int:
    if not os.getenv("GROQ_API_KEY"):
        print("SKIP: GROQ_API_KEY is not set")
        return 0
    settings = Settings.from_env()
    if settings.llm_mode != "live":
        settings = Settings(**{**settings.__dict__, "llm_mode": "live"})
    session = AdvisorSession(settings=settings, tier=PermissionTier.ADVISE)
    prompts = (
        "Record these client facts: age 35, amount 100000, horizon 8 years, maximum tolerable loss 0.20, and not borrowed money.",
        "Use the questionnaire keys to profile me: horizon 7_10y, liquidity_need over_30d, income_stability stable, emergency_fund over_6_months, invested_share under_25, drawdown_reaction hold, experience good, goal growth.",
        "Compare suitable products and build the allocation using the recorded client facts.",
    )
    for prompt in prompts:
        print(session.send(prompt))
    print(json.dumps(session.snapshot(), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
