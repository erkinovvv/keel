"""Build the submission PDFs from the Markdown docs.

    uv run --with markdown --with playwright python scripts/build_docs_pdf.py

Writes submission/Keel_Technical_Documentation.pdf (architecture, core algorithms, security design)
and submission/Keel_Security_Self_Assessment.pdf. Mermaid diagrams are rendered by mermaid.js in
headless Chrome before printing, so the PDFs need network access once.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import subprocess
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission"
BUILD = OUT / ".build"
DOCS = ROOT / "docs"

CSS = """
@page { size: A4; margin: 18mm 18mm 20mm; }
:root { --ink:#0f1b26; --ink2:#5a6773; --ink3:#8692a0; --rule:#dde2e7; --navy:#23476b; --brass:#8a6420; --sunken:#eef1f4; }
* { box-sizing: border-box; }
body { margin:0; color:var(--ink); font: 400 10pt/1.55 "Inter", "Noto Sans SC", system-ui, sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
h1 { font-size: 22pt; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 10pt; break-before: page; }
h1.first { break-before: auto; }
h2 { font-size: 13.5pt; font-weight: 600; margin: 20pt 0 6pt; letter-spacing: -0.01em; break-after: avoid; }
h3 { font-size: 11pt; font-weight: 600; margin: 14pt 0 4pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 8pt; padding-left: 16pt; }
a { color: var(--navy); text-decoration: none; }
code { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 8.6pt; background: var(--sunken); padding: 0 2pt; border-radius: 2pt; }
pre { background: var(--sunken); padding: 8pt 10pt; border-radius: 4pt; overflow: hidden; white-space: pre-wrap; font-size: 8.4pt; break-inside: avoid; }
pre code { background: none; padding: 0; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0 12pt; font-size: 8.6pt; break-inside: auto; }
tr { break-inside: avoid; }
th { text-align: left; font-weight: 600; color: var(--ink2); border-bottom: 1px solid var(--ink3); padding: 4pt 6pt 4pt 0; vertical-align: bottom; }
td { border-bottom: 1px solid var(--rule); padding: 4pt 6pt 4pt 0; vertical-align: top; }
blockquote { margin: 0 0 8pt; padding-left: 10pt; border-left: 2px solid var(--brass); color: var(--ink2); }
img { max-width: 100%; border: 1px solid var(--rule); border-radius: 4pt; }
figure { margin: 8pt 0 12pt; break-inside: avoid; }
figcaption { font-size: 8.6pt; color: var(--ink2); margin-top: 4pt; }
.mermaid { background: none; text-align: center; break-inside: avoid; margin: 8pt 0 12pt; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: space-between; }
.cover .mark { width: 34pt; height: 34pt; }
.cover h1 { font-size: 40pt; margin: 18pt 0 4pt; break-before: auto; }
.cover .sub { font-size: 15pt; color: var(--ink2); max-width: 120mm; line-height: 1.35; }
.cover .meta { font-size: 9.5pt; color: var(--ink2); border-top: 1px solid var(--ink); padding-top: 8pt; line-height: 1.6; }
.toc { break-before: page; }
.toc h2 { margin-top: 0; }
.toc ol { padding-left: 14pt; font-size: 10.5pt; line-height: 1.9; }
.toc ol ol { font-size: 9.5pt; line-height: 1.7; color: var(--ink2); }
"""

MARK = ('<svg class="mark" viewBox="0 0 32 32"><rect x="2" y="2" width="28" height="28" rx="6" fill="#0f1b26"/>'
        '<path d="M8 13h16M16 13v11M12.5 24h7" stroke="#fff" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render(md_text: str, *, first: bool = False) -> str:
    """Markdown to HTML; mermaid code fences become diagrams, image paths become absolute file URLs."""

    md_text = re.sub(r"```mermaid\n(.*?)```", lambda m: f'<pre class="mermaid">{html.escape(m.group(1))}</pre>', md_text, flags=re.S)
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    body = re.sub(r'src="(?!https?:|file:)([^"]+)"', lambda m: f'src="{(DOCS / m.group(1)).resolve().as_uri()}"', body)
    if first:
        body = body.replace("<h1>", '<h1 class="first">', 1)
    return body


def toc(parts: list[tuple[str, str]]) -> str:
    items = []
    for title, md_text in parts:
        subs = [re.sub(r"[`*]", "", h) for h in re.findall(r"^## (.+)$", md_text, flags=re.M)]
        items.append(f"<li>{html.escape(title)}<ol>{''.join(f'<li>{html.escape(s)}</li>' for s in subs)}</ol></li>")
    return f'<section class="toc"><h2>Contents</h2><ol>{"".join(items)}</ol></section>'


def cover(title: str, subtitle: str) -> str:
    today = dt.date.today().strftime("%d %B %Y")
    return f"""<section class="cover"><div>{MARK}<h1>{html.escape(title)}</h1><div class="sub">{html.escape(subtitle)}</div></div>
<div class="meta">Keel · AI wealth advisor<br>2026 Shenzhen International FinTech Competition, International Track, Topic B: Wealth Advisory Agent<br>
Team Keel, Westminster International University in Tashkent<br>{today} · source revision {commit()}</div></section>"""


OVERVIEW = """# Overview

Keel runs the workflow of a licensed wealth advisor: fact-find, risk profiling, product comparison,
explainable asset allocation, stress testing and client-confirmed execution, in a plain conversation
next to a client file. Its design rule is **the model talks, code decides**: the language model explains
and asks questions, while every number, every suitability decision and every money-moving action comes
from deterministic, tested code that the model cannot reach.

Two ideas set it apart:

- **Crash Rehearsal.** Before any money moves, the client lives through October 2007 to March 2013 with
  the exact portfolio Keel recommends, month by month on real market data, with a *Sell everything*
  button. Where the client actually sells reveals their risk tolerance; it can only lower the risk class.
- **Advice that can be checked.** Each figure links to the function that computed it and the audit record
  it was written to; the audit log is hash-chained and its head is anchored in a smart contract on
  WeBank's FISCO BCOS consortium chain.

<figure><img src="img/rehearsal.png" alt="Crash Rehearsal"><figcaption>Crash Rehearsal: the client's own portfolio replayed through 2008, with the loss it would lock in shown on the Sell button.</figcaption></figure>

<figure><img src="img/portfolio.png" alt="Recommended portfolio"><figcaption>Recommended portfolio of real Chinese public funds. Tapping a figure shows the function that computed it and its audit record.</figcaption></figure>

This document has three parts, as the competition asks: **system architecture**, **core algorithms**
and **security design**. Evaluation results (65-case red-team suite, 30 client personas on the live
model) are summarised in the security part; the full reports are in the repository under `evals/`.
"""


def page(body: str, title: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..600&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<style>{CSS}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script></head>
<body>{body}
<script>
  mermaid.initialize({{ startOnLoad: false, theme: "neutral", fontFamily: "Inter, sans-serif", flowchart: {{ useMaxWidth: true }}, sequence: {{ useMaxWidth: true }} }});
  mermaid.run({{ querySelector: ".mermaid" }}).then(() => document.body.dataset.ready = "1", (e) => {{ document.body.dataset.ready = "error: " + e; }});
  if (!document.querySelector(".mermaid")) document.body.dataset.ready = "1";
</script></body></html>"""


def print_pdf(html_text: str, name: str, footer_title: str) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    src = BUILD / f"{name}.html"
    src.write_text(html_text, encoding="utf-8")
    dest = OUT / f"{name}.pdf"
    footer = (f'<div style="font: 7.5pt Helvetica, Arial, sans-serif; color:#8692a0; width:100%; padding:0 18mm; display:flex; justify-content:space-between">'
              f'<span>Keel · {html.escape(footer_title)}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        pg = browser.new_page()
        pg.goto(src.as_uri(), wait_until="networkidle")
        for _ in range(100):
            state = pg.evaluate("document.body.dataset.ready || ''")
            if state:
                break
            pg.wait_for_timeout(200)
        if state != "1":
            raise RuntimeError(f"diagram rendering failed for {name}: {state or 'timeout'}")
        pg.evaluate("document.fonts.ready")
        pg.pdf(path=str(dest), format="A4", print_background=True, display_header_footer=True,
               header_template="<span></span>", footer_template=footer,
               margin={"top": "18mm", "bottom": "20mm", "left": "18mm", "right": "18mm"})
        browser.close()
    return dest


def main() -> None:
    arch = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8")
    ontology = (DOCS / "ONTOLOGY.md").read_text(encoding="utf-8")
    algo = (DOCS / "ALGORITHM.md").read_text(encoding="utf-8")
    sec = (DOCS / "SECURITY_SELF_ASSESSMENT.md").read_text(encoding="utf-8")

    parts = [("Overview", OVERVIEW), ("System architecture", arch), ("Advisory ontology and lifecycle", ontology), ("Core algorithms", algo), ("Security design", sec)]
    body = cover("Technical documentation", "System architecture, core algorithms and security design") + toc(parts)
    body += render(OVERVIEW, first=False)
    body += render(arch.replace("# Architecture", "# System architecture", 1))
    body += render(ontology)
    body += render(algo)
    body += render(sec.replace("# Security self-assessment", "# Security design", 1))
    tech = print_pdf(page(body, "Keel technical documentation"), "Keel_Technical_Documentation", "Technical documentation")

    body = cover("Security self-assessment", "Permission-tier implementation, controls and tests, red-team results and known risks")
    body += render(sec)
    secpdf = print_pdf(page(body, "Keel security self-assessment"), "Keel_Security_Self_Assessment", "Security self-assessment")
    for path in (tech, secpdf):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
