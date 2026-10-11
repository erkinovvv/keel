"""Client-facing Advice Report: a printable suitability record of one advisory session.

Everything in it comes from stored session state and deterministic functions; the report itself
is hashed and that hash is written to the audit chain, so a printed copy can be verified later.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from html import escape
from typing import Any

from wealth_advisor.ui.labels import CLASS_NAMES, FLAG_LABELS, explain_reason

SCENARIO_NAMES = {"2008_gfc": "2008 global financial crisis", "2020_covid": "2020 pandemic crash", "2022_rate_shock": "2022 rate shock"}
ASSET_NAMES = {"cash": "Cash", "bonds": "Bonds", "equity": "Equity", "gold": "Gold", "reits": "Real estate"}


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
        <h2>{next(number)}. Your risk profile</h2>
        <div class="facts">
          <div><span>Risk class</span><b>C{profile.investor_class} · {CLASS_NAMES[profile.investor_class]}</b></div>
          <div><span>Capacity for loss</span><b>C{profile.capacity_class}</b></div>
          <div><span>Tolerance for risk</span><b>C{profile.tolerance_class}</b></div>
          <div><span>Valid until</span><b>{profile.expires_on:%d %B %Y}</b></div>
        </div>
        <p>Your class is the lower of your capacity and your tolerance, as investor-suitability rules require.
        You may be recommended products rated up to <b>R{profile.investor_class}</b> only.</p>
        {f'<h3>Client-protection flags</h3><ul>{flags}</ul>' if flags else ''}
        <h3>Your answers</h3><ul class="cols">{reasons}</ul>
      </section>""")

    if allocation is not None:
        rows = "".join(
            f"<tr><td>{escape(products[h.product_id].name)}<small>{ASSET_NAMES.get(h.asset_class, h.asset_class)}</small></td>"
            f"<td>R{products[h.product_id].risk_class}</td><td class=r>{_pct(h.weight)}</td><td class=r>{_money(h.amount)}</td>"
            f"<td>{'<br>'.join(escape(explain_reason(c)) for c in h.reason_codes)}</td></tr>"
            for h in allocation.holdings
        )
        sections.append(f"""
      <section>
        <h2>{next(number)}. Recommended portfolio</h2>
        <div class="facts">
          <div><span>Amount</span><b>{_money(allocation.amount)}</b></div>
          <div><span>Expected return a year</span><b>{_pct(allocation.expected_return, 2)}</b></div>
          <div><span>Volatility a year</span><b>{_pct(allocation.volatility, 2)}</b></div>
          <div><span>Average fee a year</span><b>{_pct(allocation.fee, 2)}</b></div>
          <div><span>1-year value at risk (95%)</span><b>{_money(allocation.var_95_1y)}</b></div>
        </div>
        <table><thead><tr><th>Product</th><th>Risk</th><th class=r>Weight</th><th class=r>Amount</th><th>Why it was chosen</th></tr></thead><tbody>{rows}</tbody></table>
        <p class="note">Expected return and volatility are model estimates, net of product fees. They are not guaranteed.</p>
      </section>""")

    if goal:
        r, g = goal["result"], goal["input"]
        sections.append(f"""
      <section>
        <h2>{next(number)}. Your goal</h2>
        <p><b>{escape(g['name'])}</b>: {_money(r['target_nominal'])} in {g['years']} years, saving {_money(g['monthly'])} a month.</p>
        <div class="facts">
          <div><span>Chance of reaching it</span><b>{r['probability'] * 100:.0f}%</b></div>
          <div><span>Bad case (1 in 10)</span><b>{_money(r['terminal_p10'])}</b></div>
          <div><span>Median outcome</span><b>{_money(r['terminal_p50'])}</b></div>
          <div><span>Saving for an 80% chance</span><b>{_money(r['required_monthly']) + ' a month' if r['required_monthly'] is not None else 'n/a'}</b></div>
        </div>
        <p class="note">{escape('; '.join(r['assumptions']))}.</p>
      </section>""")

    if rehearsal:
        r = rehearsal
        sold = r["action"] == "sell"
        did = f"Sold in {_month(r['month'])}, {_pct(r['drawdown_at_decision'])} below the peak" if sold else f"Held through a {_pct(r['max_drawdown'])} fall (bottom in {_month(r['trough_month'])})" + (" and bought more" if r["action"] == "buy_more" else "")
        verdict = (f"Risk class lowered from C{r['previous_class']} to C{r['new_class']}" if r["new_class"] < r["previous_class"] else f"Risk class C{r['new_class']} confirmed")
        sections.append(f"""
      <section>
        <h2>{next(number)}. Crash rehearsal: what you said and what you did</h2>
        <p>Before investing, you replayed October 2007 to March 2013 month by month with real market returns, holding the recommended portfolio, and could sell at any point.</p>
        <div class="facts">
          <div><span>You said, after a 20% fall</span><b>{escape((stated_reaction or "—").replace("_", " "))}</b></div>
          <div><span>What you did</span><b>{escape(did)}</b></div>
          <div><span>Value by March 2013 if held</span><b>{_money(r['final_value_if_held'])}</b></div>
          <div><span>Value after your choice</span><b>{_money(r['final_value_of_choice'])}</b></div>
          <div><span>Result</span><b>{verdict}</b></div>
        </div>
        <p class="note">Revealed behaviour can only lower a risk class, never raise it. Data: Kenneth R. French Data Library, FRED GS10, World Bank commodity prices; US markets as a proxy.</p>
      </section>""")

    if stress:
        tolerance = client.get("max_loss", 0)
        rows = "".join(
            f"<tr><td>{escape(SCENARIO_NAMES.get(s.scenario, s.scenario.replace('_', ' ')))}</td><td class=r>−{_pct(s.loss_percent)}</td><td class=r>{_money(s.loss_amount)}</td>"
            f"<td>{'Exceeds your limit' if s.mismatch else 'Within your limit'}</td></tr>"
            for s in stress
        )
        sections.append(f"""
      <section>
        <h2>{next(number)}. Stress test</h2>
        <p>Historical shocks replayed on the recommended portfolio, compared with the {_pct(tolerance, 0)} loss you said you could accept in a bad year.</p>
        <table><thead><tr><th>Scenario</th><th class=r>Loss</th><th class=r>Amount</th><th>Against your limit</th></tr></thead><tbody>{rows}</tbody></table>
      </section>""")

    sections.append(f"""
      <section>
        <h2>Important information</h2>
        <ul>
          <li>Investments can fall as well as rise and you may get back less than you invest. Past performance does not predict future results.</li>
          <li>Products rated R4 or higher are subject to a cooling-off period before purchase.</li>
          <li>All figures were produced by deterministic, tested code; the AI assistant explains them but does not calculate them.</li>
          <li>This is a competition prototype. Fund data is public information on real Chinese mutual funds (East Money / Tiantian Fund) and may be out of date; orders run on a simulated account. It is not investment advice.</li>
        </ul>
        <div class="facts">
          <div><span>Risk disclosure</span><b>{'Signed in this session' if signed else 'Not signed'}</b></div>
          <div><span>Audit chain</span><b>{'Verified' if audit_valid else 'FAILED'} · {audit_records} records</b></div>
          <div><span>Language model</span><b>{escape(model_mode)} mode</b></div>
        </div>
      </section>""")

    body = "".join(sections)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Advice Report</title>
<link rel="icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Schibsted+Grotesk:wght@400;500;600&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<style>
  :root {{ --ink:#14211f; --ink2:#4a5b57; --ink3:#7a8a86; --line:#d9e2df; --jade:#17695a; --paper:#ffffff; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#eef2f1; color:var(--ink); font:400 14px/1.55 "Schibsted Grotesk", system-ui, sans-serif; }}
  .page {{ max-width: 820px; margin: 32px auto; background: var(--paper); padding: 56px 64px; box-shadow: 0 8px 30px rgba(10,30,26,.08); }}
  header {{ display:flex; justify-content:space-between; align-items:flex-start; border-bottom: 2px solid var(--ink); padding-bottom: 18px; margin-bottom: 8px; }}
  h1 {{ font: 500 34px/1.1 "Newsreader", Georgia, serif; margin: 0; letter-spacing: -0.01em; }}
  header p {{ margin: 6px 0 0; color: var(--ink2); }}
  .meta {{ text-align:right; font-size: 12px; color: var(--ink2); }}
  h2 {{ font: 500 21px/1.2 "Newsreader", Georgia, serif; margin: 34px 0 12px; }}
  h3 {{ font-size: 13px; margin: 18px 0 6px; color: var(--ink2); font-weight: 600; }}
  p {{ margin: 8px 0; max-width: 70ch; }}
  .facts {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 12px 0; padding: 1px 0 0 1px; }}
  .facts div {{ background: #fff; padding: 10px 12px; border: 1px solid var(--line); margin: -1px 0 0 -1px; }}
  .facts span {{ display:block; font-size: 12px; color: var(--ink3); }}
  .facts b {{ font-size: 15px; font-weight: 600; }}
  ul {{ margin: 6px 0; padding-left: 18px; }} li {{ margin: 2px 0; }}
  ul.cols {{ columns: 2; column-gap: 28px; color: var(--ink2); font-size: 13px; }}
  table {{ width:100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
  th {{ text-align:left; font-weight:500; color: var(--ink3); border-bottom: 1px solid var(--ink); padding: 6px 8px; }}
  td {{ border-bottom: 1px solid var(--line); padding: 8px; vertical-align: top; }}
  td small {{ display:block; color: var(--ink3); }}
  .r {{ text-align: right; white-space: nowrap; }}
  .note {{ font-size: 12px; color: var(--ink3); }}
  footer {{ margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--ink3); }}
  footer code {{ font-family: "IBM Plex Mono", monospace; color: var(--ink2); word-break: break-all; }}
  .toolbar {{ max-width: 820px; margin: 24px auto -12px; display:flex; justify-content:flex-end; gap: 8px; }}
  .toolbar button {{ font: 600 14px "Schibsted Grotesk", sans-serif; border:0; border-radius:10px; padding:10px 16px; background: var(--jade); color:#fff; cursor:pointer; }}
  @media print {{ body {{ background:#fff; }} .page {{ box-shadow:none; margin:0; padding: 0; max-width:none; }} .toolbar {{ display:none; }} section {{ break-inside: avoid; }} }}
  @media (max-width: 700px) {{ .page {{ padding: 28px 20px; margin: 0; }} ul.cols {{ columns: 1; }} }}
</style></head>
<body>
  <div class="toolbar"><button id="printReport" type="button">Save as PDF</button></div>
  <script src="/static/report.js"></script>
  <main class="page">
    <header>
      <div><h1>Advice Report</h1><p>Suitability record of your advisory session</p></div>
      <div class="meta">Keel<br>{now:%d %B %Y, %H:%M} UTC<br>Report {digest[:12]}</div>
    </header>
    {body}
    <footer>Report fingerprint (SHA-256): <code>{digest}</code><br>This fingerprint is recorded in the session's hash-chained audit log, so any change to this report can be detected.</footer>
  </main>
</body></html>"""
    return html, digest
