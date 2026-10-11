"""Streamlit demo UI: advisory chat plus live, deterministic advisory panels.

Run from the repo root:  uv run streamlit run src/wealth_advisor/ui/app.py
"""

from __future__ import annotations

import importlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from wealth_advisor.allocation import build_allocation
from wealth_advisor.audit import AuditLogger, verify_audit_log
from wealth_advisor.catalog import compare_products, load_catalog
from wealth_advisor.config import Settings
from wealth_advisor.profiling import QUESTIONNAIRE, profile_investor
from wealth_advisor.stress import SCENARIOS, stress_test
from wealth_advisor.ui.labels import CLASS_NAMES, FLAG_LABELS, explain_reason, humanize, question_label

# Chart colors: one sequential hue for magnitude, a reserved status red for "exceeds tolerance".
BAR = "#2a78d6"
CRITICAL = "#e34948"
MUTED = "#8a8984"

SCENARIO_NAMES = {
    "2008_gfc": "2008 Global Financial Crisis",
    "2020_covid": "2020 COVID crash",
    "2022_rate_shock": "2022 Rate shock",
}

DISCLAIMER = (
    "This is a hackathon prototype using a mock product catalog. Projections are model estimates, "
    "not guarantees; past performance does not predict future results. Not investment advice."
)

st.set_page_config(page_title="Wealth Advisor Agent", page_icon="📈", layout="wide")


@st.cache_resource
def _settings() -> Settings:
    return Settings.from_env()


@st.cache_data
def _catalog():
    return load_catalog()


def _audit() -> AuditLogger:
    return AuditLogger(_settings().audit_log)


def _session_class():
    """Return AdvisorSession if the backend exposes it yet (built in parallel by the core team)."""

    for module_name in ("wealth_advisor.session", "wealth_advisor.agent"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        if hasattr(module, "AdvisorSession"):
            return module.AdvisorSession
    return None


# ---------------------------------------------------------------- sidebar: KYC + profiling


def sidebar() -> None:
    st.sidebar.header("1 · Know your client")
    with st.sidebar.form("kyc"):
        age = st.number_input("Age", min_value=18, max_value=100, value=35)
        amount = st.number_input("Amount to invest", min_value=1_000, max_value=10_000_000, value=100_000, step=5_000)
        horizon_years = st.slider("Investment horizon (years)", 1, 30, 10)
        max_loss = st.slider("Largest one-year loss you could accept (%)", 5, 50, 20)
        borrowed = st.checkbox("Part of this money is borrowed")
        st.markdown("**Risk questionnaire**")
        answers = {}
        for key, question in QUESTIONNAIRE.items():
            options = list(question["options"])
            answers[key] = st.selectbox(question_label(key), options, index=len(options) // 2, format_func=humanize, key=f"q_{key}")
        submitted = st.form_submit_button("Assess my risk profile", type="primary", width="stretch")

    if submitted:
        try:
            profile = profile_investor(answers, age=int(age), borrowed_money=borrowed)
        except (ValueError, TypeError) as exc:
            st.sidebar.error(f"Could not score the questionnaire: {exc}")
            return
        st.session_state.profile = profile
        st.session_state.client = {
            "amount": float(amount),
            "horizon_years": int(horizon_years),
            "max_loss": max_loss / 100,
            "age": int(age),
        }
        st.session_state.what_if_class = profile.investor_class
        _audit().append("ui_profile_assessed", {"profile": profile.as_dict(), "client": st.session_state.client})


# ---------------------------------------------------------------- panels


def profile_card(profile) -> None:
    left, mid, right = st.columns([1.2, 1, 1])
    left.metric("Risk class", f"C{profile.investor_class} · {CLASS_NAMES[profile.investor_class]}")
    mid.metric("Risk capacity", f"C{profile.capacity_class}", help="Objective ability to bear losses: horizon, income, cash buffer, share of wealth.")
    right.metric("Risk tolerance", f"C{profile.tolerance_class}", help="Attitude to risk: reaction to drawdowns, experience, goal.")
    st.caption(
        f"Your class is the **lower** of capacity and tolerance (suitability rule). "
        f"You may only be recommended products up to **R{profile.investor_class}**. "
        f"Profile valid until {profile.expires_on:%d %b %Y}."
    )
    for flag in profile.vulnerability_flags:
        st.warning(FLAG_LABELS.get(flag, flag), icon="⚠️")
    with st.expander("Why this class? (reason codes)"):
        for code in profile.reason_codes:
            st.markdown(f"- `{code}` — {explain_reason(code)}")


def allocation_chart(allocation) -> alt.Chart:
    data = pd.DataFrame(
        [{"Asset class": k.capitalize(), "Weight": v} for k, v in allocation.strategic_weights.items() if v > 0]
    ).sort_values("Weight", ascending=False)
    base = alt.Chart(data).encode(
        y=alt.Y("Asset class:N", sort="-x", title=None),
        x=alt.X("Weight:Q", axis=alt.Axis(format="%", grid=False), title=None),
        tooltip=[alt.Tooltip("Asset class:N"), alt.Tooltip("Weight:Q", format=".1%")],
    )
    bars = base.mark_bar(color=BAR, cornerRadiusEnd=4, height=22)
    labels = base.mark_text(align="left", dx=6).encode(text=alt.Text("Weight:Q", format=".0%"))
    return (bars + labels).properties(height=40 * len(data) + 20)


def portfolio_tab(profile, client) -> None:
    profile_card(profile)
    st.divider()
    st.subheader("2 · Recommended allocation")

    c1, c2 = st.columns(2)
    amount = c1.slider(
        "What if I invest…", 1_000, max(int(client["amount"]) * 3, 10_000), int(client["amount"]), step=1_000,
        help="Re-runs the deterministic allocation instantly — no AI involved.",
    )
    level = c2.select_slider(
        "What if I take less risk…",
        options=list(range(1, profile.investor_class + 1)),
        value=min(st.session_state.get("what_if_class", profile.investor_class), profile.investor_class),
        format_func=lambda c: f"C{c} {CLASS_NAMES[c]}",
        help="You can always choose a lower risk level. Higher than your assessed class is blocked by the suitability rule.",
    )
    st.session_state.what_if_class = level

    try:
        allocation = build_allocation(float(amount), level, _catalog())
    except ValueError as exc:
        st.error(f"No compliant allocation for this input: {exc}")
        return
    st.session_state.allocation = allocation

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Expected return / yr", f"{allocation.expected_return:.2%}", help="Net of product fees. Model estimate, not a guarantee.")
    k2.metric("Volatility / yr", f"{allocation.volatility:.2%}")
    k3.metric("Weighted fee", f"{allocation.fee:.2%}")
    k4.metric("1-yr VaR (95%)", f"{allocation.var_95_1y:,.0f}", help="Parametric, zero-mean: in 19 of 20 years the loss should not exceed this amount.")

    chart_col, table_col = st.columns([1, 1.4])
    with chart_col:
        st.markdown("**By asset class**")
        st.altair_chart(allocation_chart(allocation), width="stretch")
    with table_col:
        st.markdown("**Holdings**")
        names = {p.id: p.name for p in _catalog()}
        risks = {p.id: p.risk_class for p in _catalog()}
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Product": names[h.product_id],
                        "Asset class": h.asset_class.capitalize(),
                        "Risk": f"R{risks[h.product_id]}",
                        "Weight": h.weight,
                        "Amount": h.amount,
                    }
                    for h in allocation.holdings
                ]
            ),
            column_config={
                "Weight": st.column_config.NumberColumn(format="percent"),
                "Amount": st.column_config.NumberColumn(format="%,.0f"),
            },
            hide_index=True,
            width="stretch",
        )
        for holding in allocation.holdings:
            with st.expander(f"Why {names[holding.product_id]}?"):
                for code in holding.reason_codes:
                    st.markdown(f"- {explain_reason(code)}")


def compare_tab(profile, client) -> None:
    st.subheader("Product comparison")
    st.caption(f"Only products suitable for C{profile.investor_class} (≤ R{profile.investor_class}) are shown. Fee drag = cost of fees over your {client['horizon_years']}-year horizon on {client['amount']:,.0f}.")
    asset = st.segmented_control("Asset class", ["All", "cash", "bonds", "equity", "gold", "reits"], default="All")
    rows = compare_products(
        _catalog(), client["amount"], client["horizon_years"], profile.investor_class,
        asset_class=None if asset in (None, "All") else asset,
    )
    if not rows:
        st.info("No suitable products in this asset class for your risk class.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Product": r.name,
                    "Class": r.asset_class.capitalize(),
                    "Risk": f"R{r.risk_class}",
                    "Exp. return": r.expected_return,
                    "Fee": r.fee,
                    "Net return": r.net_return,
                    "Volatility": r.volatility,
                    "Return / risk": r.sharpe_like,
                    "Fee drag": r.fee_drag,
                    "Liquidity (days)": r.liquidity_days,
                }
                for r in rows
            ]
        ),
        column_config={
            **{c: st.column_config.NumberColumn(format="percent") for c in ("Exp. return", "Fee", "Net return", "Volatility")},
            "Return / risk": st.column_config.NumberColumn(format="%.2f"),
            "Fee drag": st.column_config.NumberColumn(format="%,.0f"),
        },
        hide_index=True,
        width="stretch",
    )
    hidden = [p for p in _catalog() if p.risk_class > profile.investor_class]
    if hidden:
        st.caption("Not shown (above your risk class): " + ", ".join(f"{p.name} (R{p.risk_class})" for p in hidden))


def stress_tab(client) -> None:
    allocation = st.session_state.get("allocation")
    if allocation is None:
        st.info("Open the Portfolio tab first to build an allocation.")
        return
    st.subheader("Stress test — how would this portfolio have fared?")
    results = [stress_test(allocation, key, max_tolerable_loss=client["max_loss"]) for key in SCENARIOS]
    data = pd.DataFrame(
        [
            {
                "Scenario": SCENARIO_NAMES.get(r.scenario, r.scenario),
                "Loss": r.loss_percent,
                "Loss amount": r.loss_amount,
                "Status": "Exceeds your limit" if r.mismatch else "Within your limit",
            }
            for r in results
        ]
    )
    tolerance = client["max_loss"]
    base = alt.Chart(data).encode(
        y=alt.Y("Scenario:N", title=None, sort=None),
        x=alt.X("Loss:Q", axis=alt.Axis(format="%", grid=False), title="Portfolio loss", scale=alt.Scale(domain=[0, max(tolerance, data["Loss"].max()) * 1.25])),
        tooltip=["Scenario:N", alt.Tooltip("Loss:Q", format=".1%"), alt.Tooltip("Loss amount:Q", format=",.0f"), "Status:N"],
    )
    bars = base.mark_bar(cornerRadiusEnd=4, height=22).encode(
        color=alt.Color("Status:N", scale=alt.Scale(domain=["Within your limit", "Exceeds your limit"], range=[BAR, CRITICAL]), legend=alt.Legend(orient="top", title=None))
    )
    labels = base.mark_text(align="left", dx=6).encode(text=alt.Text("Loss:Q", format=".1%"))
    rule = alt.Chart(pd.DataFrame({"x": [tolerance]})).mark_rule(strokeDash=[4, 3], color=MUTED, strokeWidth=2).encode(x="x:Q")
    rule_label = alt.Chart(pd.DataFrame({"x": [tolerance], "t": [f"Your limit {tolerance:.0%}"]})).mark_text(align="left", dx=4, dy=-8, color=MUTED, baseline="bottom").encode(x="x:Q", y=alt.value(0), text="t:N")
    st.altair_chart((bars + labels + rule + rule_label).properties(height=170), width="stretch")

    breaches = [r for r in results if r.mismatch]
    if breaches:
        st.error(
            f"⚠️ In {len(breaches)} historical scenario(s) this portfolio would lose more than the "
            f"{tolerance:.0%} you said you could accept. Consider a lower risk level in the Portfolio tab.",
        )
    else:
        st.success(f"✅ In all scenarios the loss stays within your {tolerance:.0%} limit.")
    st.caption("Shocks are applied per asset class from historical peak-to-trough moves; real losses can differ.")


def chat_tab() -> None:
    session_cls = _session_class()
    if session_cls is None:
        st.info("The conversational advisor is being wired to the agent backend (AdvisorSession). The panels on the other tabs are fully functional.")
        return
    if "advisor" not in st.session_state:
        st.session_state.advisor = session_cls()
        st.session_state.chat = []
    for message in st.session_state.chat:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    if prompt := st.chat_input("Ask your advisor…"):
        st.session_state.chat.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"), st.spinner("Thinking…"):
            try:
                reply = st.session_state.advisor.send(prompt)
            except Exception as exc:  # surface backend errors instead of a blank screen
                reply = f"Sorry, something went wrong: `{exc}`"
            st.markdown(reply)
        st.session_state.chat.append({"role": "assistant", "content": reply})


def audit_tab() -> None:
    path = Path(_settings().audit_log)
    st.subheader("Audit trail")
    st.caption("Every model call, tool call and decision is appended to a hash-chained log: editing any past record breaks the chain.")
    valid, reason = verify_audit_log(path)
    (st.success if valid else st.error)(f"{'✅' if valid else '❌'} {reason}")
    if not path.exists():
        return
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Time (UTC)": r["timestamp"][:19].replace("T", " "),
                    "Event": r["event"],
                    "Details": json.dumps(r.get("details", {}))[:160],
                    "Hash": r["hash"][:12],
                    "Prev": (r.get("prev_hash") or "—")[:12],
                }
                for r in reversed(records[-200:])
            ]
        ),
        hide_index=True,
        width="stretch",
    )


# ---------------------------------------------------------------- page


def main() -> None:
    st.title("Wealth Advisor Agent")
    st.caption("KYC → risk profiling → suitability-checked comparison → explainable allocation → stress test → confirmed execution. Every number is computed by audited code, never by the AI.")
    sidebar()

    tabs = st.tabs(["💬 Advisor", "📊 Portfolio", "⚖️ Compare", "🌪️ Stress test", "🔒 Audit trail"])
    with tabs[0]:
        chat_tab()
    profile = st.session_state.get("profile")
    client = st.session_state.get("client")
    # Portfolio renders before Stress test on every rerun, so the stress tab sees the current allocation.
    panels = (
        lambda: portfolio_tab(profile, client),
        lambda: compare_tab(profile, client),
        lambda: stress_tab(client),
    )
    for tab, render in zip(tabs[1:4], panels):
        with tab:
            if profile is None:
                st.info("👈 Complete the risk questionnaire in the sidebar to see your personalised analysis.")
            else:
                render()
    with tabs[4]:
        audit_tab()
    st.divider()
    st.caption(f"{DISCLAIMER} · {date.today():%Y-%m-%d}")


main()
