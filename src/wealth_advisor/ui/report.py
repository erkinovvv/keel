"""Client-facing Advice Report: a printable suitability record of one advisory session.

Everything in it comes from stored session state and deterministic functions; the report itself
is hashed and that hash is written to the audit chain, so a printed copy can be verified later.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from html import escape
from typing import Any

from wealth_advisor.ui.labels import CLASS_NAMES, FLAG_LABELS, RISK_NAMES, explain_reason

SCENARIO_NAMES = {"2008_gfc": "2008 global financial crisis", "2020_covid": "2020 pandemic crash", "2022_rate_shock": "2022 interest-rate jump"}
ASSET_NAMES = {"cash": "Cash", "bonds": "Bonds", "equity": "Shares", "gold": "Gold", "reits": "Real estate"}


def _pct(v: float, d: int = 1) -> str:
    return f"{v * 100:.{d}f}%"


def _month(ym: str) -> str:
    return datetime.strptime(ym, "%Y-%m").strftime("%B %Y")


def _money(v: float) -> str:
    return f"{v:,.0f}"


def render_report(
    *,
    profile: Any,
    client: dict[str, Any],
    allocation: Any | None,
    stress: list[Any],
    goal: dict[str, Any] | None,
    rehearsal: dict[str, Any] | None = None,
    stated_reaction: str | None = None,
    products: dict[str, Any],
    audit_valid: bool,
    audit_records: int,
    signed: bool,
    model_mode: str,
) -> tuple[str, str]:
    """Return (html, sha256 of the report body)."""

    now = datetime.now(timezone.utc)
    sections: list[str] = []
    number = iter(range(1, 20))

    flags = "".join(f"<li>{escape(FLAG_LABELS.get(f, f))}</li>" for f in profile.vulnerability_flags)
    reasons = "".join(f"<li>{escape(explain_reason(code))}</li>" for code in profile.reason_codes)
    sections.append(f"""
      <section>
        <h2>{next(number)}. Your risk level</h2>
        <div class="facts">
          <div><span>Your risk level</span><b>{CLASS_NAMES[profile.investor_class]} ({profile.investor_class} of 5)</b></div>
          <div><span>What your money situation allows</span><b>{CLASS_NAMES[profile.capacity_class]}</b></div>
          <div><span>Risk you feel comfortable with</span><b>{CLASS_NAMES[profile.tolerance_class]}</b></div>
          <div><span>Answers valid until</span><b>{profile.expires_on:%d %B %Y}</b></div>
        </div>
        <p>To keep you safe we use the lower of the two, as Chinese investor-suitability rules require.
        We only suggest funds that are {RISK_NAMES[profile.investor_class]} or safer.</p>
        {f'<h3>Protection rules applied</h3><ul>{flags}</ul>' if flags else ''}
        <h3>Your answers</h3><ul class="cols">{reasons}</ul>
      </section>""")

    if allocation is not None:
        rows = "".join(
            f"<tr><td>{escape(products[h.product_id].name)}<small>{ASSET_NAMES.get(h.asset_class, h.asset_class)}</small></td>"
            f"<td>{RISK_NAMES[products[h.product_id].risk_class].capitalize()}</td><td class=r>{_pct(h.weight)}</td><td class=r>{_money(h.amount)}</td>"
            f"<td>{'<br>'.join(escape(explain_reason(c)) for c in h.reason_codes)}</td></tr>"
            for h in allocation.holdings
        )
        sections.append(f"""
      <section>
        <h2>{next(number)}. Your investment plan</h2>
        <div class="facts">
          <div><span>You invest</span><b>{_money(allocation.amount)}</b></div>
          <div><span>May grow each year</span><b>{_pct(allocation.expected_return)}</b></div>
          <div><span>Normal ups and downs</span><b>±{_pct(allocation.volatility)}</b></div>
          <div><span>Fund fees each year</span><b>{_pct(allocation.fee, 2)}</b></div>
          <div><span>Could lose in a bad year (1 in 20)</span><b>{_money(allocation.var_95_1y)}</b></div>
        </div>
        <table><thead><tr><th>Fund</th><th>Risk</th><th class=r>Share</th><th class=r>Amount</th><th>Why we chose it</th></tr></thead><tbody>{rows}</tbody></table>
        <p class="note">Growth and ups and downs are estimates after fund fees. They are not promises.</p>
      </section>""")

    if goal:
        r, g = goal["result"], goal["input"]
        sections.append(f"""
      <section>
        <h2>{next(number)}. Your goal</h2>
        <p><b>{escape(g['name'])}</b>: {_money(r['target_nominal'])} in {g['years']} years, saving {_money(g['monthly'])} a month.</p>
        <div class="facts">
          <div><span>Chance of reaching it</span><b>{r['probability'] * 100:.0f}%</b></div>
          <div><span>If markets go badly</span><b>{_money(r['terminal_p10'])}</b></div>
          <div><span>Most likely</span><b>{_money(r['terminal_p50'])}</b></div>
          <div><span>Monthly amount for an 8 in 10 chance</span><b>{_money(r['required_monthly']) + ' a month' if r['required_monthly'] is not None else '—'}</b></div>
        </div>
        <p class="note">Based on 5,000 possible futures. Real markets can crash harder than this model expects. Taxes are not included.</p>
      </section>""")

    if rehearsal:
        r = rehearsal
        sold = r["action"] == "sell"
        did = f"Sold in {_month(r['month'])}, when it was {_pct(r['drawdown_at_decision'])} down" if sold else f"Stayed in through a {_pct(r['max_drawdown'])} fall (lowest in {_month(r['trough_month'])})" + (" and bought more" if r["action"] == "buy_more" else "")
        verdict = (f"Risk level lowered from {CLASS_NAMES[r['previous_class']]} to {CLASS_NAMES[r['new_class']]}" if r["new_class"] < r["previous_class"] else f"Risk level {CLASS_NAMES[r['new_class']]} confirmed")
        sections.append(f"""
      <section>
        <h2>{next(number)}. 2008 crash test: what you said and what you did</h2>
        <p>Before investing, you watched your plan go through October 2007 to March 2013, month by month, with real market data, and could sell at any moment.</p>
        <div class="facts">
          <div><span>You said, after a 20% fall</span><b>{escape((stated_reaction or "—").replace("_", " "))}</b></div>
          <div><span>What you did</span><b>{escape(did)}</b></div>
          <div><span>Value by March 2013 if you waited</span><b>{_money(r['final_value_if_held'])}</b></div>
          <div><span>Value after your choice</span><b>{_money(r['final_value_of_choice'])}</b></div>
          <div><span>Result</span><b>{verdict}</b></div>
        </div>
        <p class="note">The test can only make your plan safer, never riskier. Data: Kenneth R. French Data Library, FRED, World Bank.</p>
      </section>""")

    if stress:
        tolerance = client.get("max_loss", 0)
        rows = "".join(
            f"<tr><td>{escape(SCENARIO_NAMES.get(s.scenario, s.scenario.replace('_', ' ')))}</td><td class=r>−{_pct(s.loss_percent)}</td><td class=r>{_money(s.loss_amount)}</td>"
            f"<td>{'More than your limit' if s.mismatch else 'Within your limit'}</td></tr>"
            for s in stress
        )
        sections.append(f"""
      <section>
        <h2>{next(number)}. Past crises</h2>
        <p>Three real crises replayed on your plan, compared with the {_pct(tolerance, 0)} you said you could lose in a bad year.</p>
        <table><thead><tr><th>Crisis</th><th class=r>Fall</th><th class=r>Amount</th><th>Your limit</th></tr></thead><tbody>{rows}</tbody></table>
      </section>""")

    sections.append(f"""
      <section>
        <h2>Important information</h2>
        <ul>
          <li>Investments can go down as well as up. You may get back less than you put in. The past does not predict the future.</li>
          <li>Medium to high and high risk funds wait 24 hours before they are bought.</li>
          <li>Every number was calculated by tested code. The AI advisor explains the numbers but does not calculate them.</li>
          <li>This is a competition prototype. Fund data is public information on real Chinese mutual funds (East Money / Tiantian Fund) and may be out of date; orders run on a simulated account. It is not investment advice.</li>
        </ul>
        <div class="facts">
          <div><span>Risk notice</span><b>{'Signed' if signed else 'Not signed'}</b></div>
          <div><span>Activity log</span><b>{'Checked, unchanged' if audit_valid else 'CHANGED'}, {audit_records} records</b></div>
          <div><span>AI model</span><b>{escape(model_mode)} mode</b></div>
        </div>
      </section>""")

    body = "".join(sections)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Advice Report</title>
<link rel="icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..600&family=Noto+Sans+SC:wght@400;500;600&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<style>
  :root {{ --ink:#0f1b26; --ink2:#5a6773; --ink3:#8692a0; --line:#dde2e7; --brass:#8a6420; --paper:#ffffff; --sans:"Inter","Noto Sans SC","PingFang SC",system-ui,sans-serif; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#f5f6f7; color:var(--ink); font:400 16px/1.55 var(--sans); font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; }}
  .page {{ max-width: 820px; margin: 32px auto; background: var(--paper); padding: 56px 64px; border: 1px solid var(--line); }}
  header {{ display:flex; justify-content:space-between; align-items:flex-start; border-bottom: 1px solid var(--ink); padding-bottom: 18px; margin-bottom: 8px; }}
  h1 {{ font: 600 30px/1.15 var(--sans); margin: 0; letter-spacing: -0.02em; }}
  header p {{ margin: 6px 0 0; color: var(--ink2); }}
  .meta {{ text-align:right; font-size: 14px; color: var(--ink2); }}
  h2 {{ font: 600 18px/1.3 var(--sans); margin: 34px 0 12px; letter-spacing: -0.01em; }}
  h3 {{ font-size: 14px; margin: 18px 0 6px; color: var(--ink2); font-weight: 600; }}
  p {{ margin: 8px 0; max-width: 70ch; }}
  .facts {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 12px 0; padding: 1px 0 0 1px; }}
  .facts div {{ background: #fff; padding: 10px 12px; border: 1px solid var(--line); margin: -1px 0 0 -1px; }}
  .facts span {{ display:block; font-size: 14px; color: var(--ink3); }}
  .facts b {{ font-size: 17px; font-weight: 600; }}
  ul {{ margin: 6px 0; padding-left: 18px; }} li {{ margin: 2px 0; }}
  ul.cols {{ columns: 2; column-gap: 28px; color: var(--ink2); font-size: 14px; }}
  table {{ width:100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }}
  th {{ text-align:left; font-weight:500; color: var(--ink3); border-bottom: 1px solid var(--ink); padding: 6px 8px; }}
  td {{ border-bottom: 1px solid var(--line); padding: 8px; vertical-align: top; }}
  td small {{ display:block; color: var(--ink3); }}
  .r {{ text-align: right; white-space: nowrap; }}
  .note {{ font-size: 14px; color: var(--ink3); }}
  footer {{ margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 14px; color: var(--ink3); }}
  footer code {{ font-family: "IBM Plex Mono", monospace; color: var(--ink2); word-break: break-all; }}
  .toolbar {{ max-width: 820px; margin: 24px auto -12px; display:flex; justify-content:flex-end; gap: 8px; }}
  .toolbar button {{ font: 600 14px var(--sans); border:0; border-radius:6px; padding:10px 16px; background: var(--brass); color:#fff; cursor:pointer; }}
  @media print {{ body {{ background:#fff; }} .page {{ box-shadow:none; margin:0; padding: 0; max-width:none; }} .toolbar {{ display:none; }} section {{ break-inside: avoid; }} }}
  @media (max-width: 700px) {{ .page {{ padding: 28px 20px; margin: 0; }} ul.cols {{ columns: 1; }} }}
</style></head>
<body>
  <div class="toolbar"><button id="printReport" type="button">Save as PDF</button></div>
  <script src="/static/report.js"></script>
  <main class="page">
    <header>
      <div><h1>Your Advice Report</h1><p>What we suggested, and why</p></div>
      <div class="meta">Keel<br>{now:%d %B %Y, %H:%M} UTC<br>Report {digest[:12]}</div>
    </header>
    {body}
    <footer>Report fingerprint: <code>{digest}</code><br>This fingerprint is saved in your activity log, so any change to this report would show.</footer>
  </main>
</body></html>"""
    return html, digest
