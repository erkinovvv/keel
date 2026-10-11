"""Terminal demo for the M1 deterministic advisory flow."""

from __future__ import annotations

import argparse
import json

from rich.console import Console
from rich.table import Table

from .agent import AdvisorAgent
from .allocation import build_allocation
from .audit import AuditLogger, verify_audit_log
from .catalog import compare_products, load_catalog
from .config import Settings
from .profiling import profile_investor
from .stress import stress_test


DEMO_ANSWERS = {
    "horizon": "7_10y",
    "income_stability": "stable",
    "emergency_fund": "over_6_months",
    "invested_share": "under_25",
    "drawdown_reaction": "hold",
    "experience": "good",
    "goal": "growth",
}


def run_demo(settings: Settings) -> None:
    console = Console()
    audit = AuditLogger(settings.audit_log)
    agent = AdvisorAgent(audit=audit, max_steps=settings.max_tool_steps)
    console.print(agent.run("Explain how you will build a suitable advisory plan."))
    profile = profile_investor(DEMO_ANSWERS, age=42)
    catalog = load_catalog()
    comparisons = compare_products(catalog, 100_000, 10, profile.investor_class)
    allocation = build_allocation(100_000, profile.investor_class, catalog)
    stress = stress_test(allocation, "2008_gfc", max_tolerable_loss=0.25)
    audit.append("advisory_flow", {"profile": profile.as_dict(), "allocation": allocation.as_dict(), "stress": stress.as_dict()})
    console.print(f"Profile: {profile.class_code}; capacity C{profile.capacity_class}; tolerance C{profile.tolerance_class}")
    table = Table("Product", "Risk", "Net return", "Fee drag")
    for item in comparisons[:5]:
        table.add_row(item.product_id, f"R{item.risk_class}", f"{item.net_return:.2%}", f"{item.fee_drag:,.2f}")
    console.print(table)
    console.print(f"Allocation expected return: {allocation.expected_return:.2%}; volatility: {allocation.volatility:.2%}; 95% VaR: {allocation.var_95_1y:,.2f}")
    console.print(f"2008 GFC loss: {stress.loss_percent:.2%} ({stress.loss_amount:,.2f}); mismatch={stress.mismatch}")
    valid, reason = verify_audit_log(settings.audit_log)
    console.print(f"Audit: {reason} ({valid})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wealth Advisory Agent demo")
    parser.add_argument("--verify-audit", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.verify_audit:
        valid, reason = verify_audit_log(settings.audit_log)
        print(json.dumps({"valid": valid, "reason": reason}))
        return
    run_demo(settings)

