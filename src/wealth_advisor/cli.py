"""Interactive chat and deterministic demo for the advisory agent."""

from __future__ import annotations

import argparse
import json

from rich.console import Console
from rich.table import Table

from .allocation import build_allocation
from .audit import AuditLogger, verify_audit_log
from .catalog import compare_products, load_catalog
from .config import Settings
from .permissions import PermissionTier
from .profiling import profile_investor
from .session import AdvisorSession
from .stress import stress_test


DEMO_ANSWERS = {
    "horizon": "7_10y",
    "liquidity_need": "over_30d",
    "income_stability": "stable",
    "emergency_fund": "over_6_months",
    "invested_share": "under_25",
    "drawdown_reaction": "hold",
    "experience": "good",
    "goal": "growth",
}


def run_chat(settings: Settings) -> None:
    """Run a multi-turn terminal conversation backed by one AdvisorSession."""

    console = Console()
    session = AdvisorSession(settings=settings, tier=PermissionTier.ADVISE)
    console.print("Wealth Advisor chat. Type 'quit' to exit.")
    while True:
        message = console.input("[bold]You[/bold] ")
        if message.strip().lower() in {"quit", "exit"}:
            break
        try:
            console.print(f"[bold]Advisor[/bold] {session.send(message)}")
        except Exception as exc:
            console.print(f"[red]Session error:[/red] {exc}")


def run_demo(settings: Settings) -> None:
    """Run the scripted M1 flow while using the session-owned state."""

    console = Console()
    session = AdvisorSession(settings=settings, tier=PermissionTier.ADVISE)
    console.print(session.send("Explain how you will build a suitable advisory plan."))
    session.dispatcher.dispatch("profile_investor", {"answers": DEMO_ANSWERS, "age": 42})
    catalog = load_catalog()
    comparisons = compare_products(catalog, 100_000, 10, session.state.profile.investor_class)
    allocation = build_allocation(100_000, session.state.profile.investor_class, catalog)
    session.state.amount = 100_000
    session.state.horizon_years = 10
    session.state.allocations["allocation-1"] = allocation
    stress = stress_test(allocation, "2008_gfc", max_tolerable_loss=0.25)
    session.state.stress_results["stress-1"] = stress
    session.audit.append("advisory_flow", {"profile": session.state.profile.as_dict(), "allocation": allocation.as_dict(), "stress": stress.as_dict()})
    console.print(f"Profile: {session.state.profile.class_code}; capacity C{session.state.profile.capacity_class}; tolerance C{session.state.profile.tolerance_class}")
    table = Table("Product", "Risk", "Net return", "Fee drag")
    for item in comparisons[:5]:
        table.add_row(item.product_id, f"R{item.risk_class}", f"{item.net_return:.2%}", f"{item.fee_drag:,.2f}")
    console.print(table)
    console.print(f"Allocation expected return: {allocation.expected_return:.2%}; volatility: {allocation.volatility:.2%}; parametric 95% VaR: {allocation.var_95_1y_parametric:,.2f}")
    console.print(f"2008 GFC loss: {stress.loss_percent:.2%} ({stress.loss_amount:,.2f}); mismatch={stress.mismatch}")
    valid, reason = verify_audit_log(settings.audit_log)
    console.print(f"Audit: {reason} ({valid})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wealth Advisory Agent")
    parser.add_argument("--verify-audit", action="store_true")
    parser.add_argument("command", nargs="?", choices=("chat", "demo"), default="demo")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.verify_audit:
        valid, reason = verify_audit_log(settings.audit_log)
        print(json.dumps({"valid": valid, "reason": reason}))
    elif args.command == "chat":
        run_chat(settings)
    else:
        run_demo(settings)
