"""Record the captioned product demo video (about four minutes).

    LLM_MODE=live PORT=8601 uv run wealth-advisor-ui        # in another terminal, with keys in .env
    scripts/fisco_chain.sh start                             # for the on-chain proof scene
    uv run --with playwright --with imageio-ffmpeg python scripts/record_demo.py --url http://127.0.0.1:8601

Writes submission/Keel_Demo.mp4. Captions are drawn into the page, so the video needs no editing.
The two chat turns use the live model; everything else is deterministic.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission"
W, H = 1440, 900

OVERLAY = """
(() => {
  if (document.getElementById("demoCap")) return;
  const cap = document.createElement("div");
  cap.id = "demoCap";
  Object.assign(cap.style, {
    position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: 9999,
    maxWidth: "960px", padding: "14px 22px", borderRadius: "8px", background: "rgba(15,27,38,.94)",
    color: "#fff", font: "500 21px/1.4 Inter, system-ui, sans-serif", textAlign: "center",
    boxShadow: "0 10px 30px rgba(0,0,0,.25)", transition: "opacity .25s", opacity: "0", pointerEvents: "none",
  });
  document.body.append(cap);
  const card = document.createElement("div");
  card.id = "demoCard";
  Object.assign(card.style, {
    position: "fixed", inset: "0", zIndex: 10000, background: "#0f1b26", color: "#fff", display: "none",
    flexDirection: "column", justifyContent: "center", padding: "0 140px", font: "400 24px/1.5 Inter, system-ui, sans-serif",
  });
  document.body.append(card);
})();
"""


# Captions sit at the bottom, or top right while the full-screen rehearsal is open so the buttons stay visible.
SHOW = """(t) => {
  const c = document.getElementById('demoCap');
  const stage = document.querySelector('.theater');
  Object.assign(c.style, stage
    ? { top: '110px', bottom: 'auto', left: 'auto', right: '72px', transform: 'none', maxWidth: '520px', textAlign: 'left' }
    : { top: 'auto', bottom: '28px', left: '50%', right: 'auto', transform: 'translateX(-50%)', maxWidth: '960px', textAlign: 'center' });
  c.textContent = t; c.style.opacity = '1';
}"""


def overlay(pg: Page) -> None:
    pg.evaluate(OVERLAY)


def cap(pg: Page, text: str, ms: int = 3800) -> None:
    """Show a caption, keep it for `ms`, then fade it out."""

    overlay(pg)
    pg.evaluate(SHOW, text)
    pg.wait_for_timeout(ms)
    pg.evaluate("() => { document.getElementById('demoCap').style.opacity = '0'; }")
    pg.wait_for_timeout(250)


def caption_on(pg: Page, text: str) -> None:
    overlay(pg)
    pg.evaluate(SHOW, text)


def caption_off(pg: Page) -> None:
    pg.evaluate("() => { const c = document.getElementById('demoCap'); if (c) c.style.opacity = '0'; }")


def card(pg: Page, title: str, lines: list[str], ms: int) -> None:
    overlay(pg)
    html = (f'<div style="font:600 64px/1.1 Inter,sans-serif;letter-spacing:-.02em;margin-bottom:22px">{title}</div>'
            + "".join(f'<div style="color:#a6b1bc;margin-top:6px">{line}</div>' for line in lines))
    pg.evaluate("(h) => { const c = document.getElementById('demoCard'); c.innerHTML = h; c.style.display = 'flex'; }", html)
    pg.wait_for_timeout(ms)
    pg.evaluate("() => { document.getElementById('demoCard').style.display = 'none'; }")


def chat(pg: Page, text: str, wait_reply_s: int = 60) -> None:
    before = pg.locator("#thread .msg-advisor").count()
    pg.click("#chatInput")
    pg.keyboard.type(text, delay=18)
    pg.wait_for_timeout(400)
    pg.keyboard.press("Enter")
    deadline = time.time() + wait_reply_s
    while time.time() < deadline:
        if pg.locator("#thread .msg-advisor").count() > before and not pg.locator("#thread .typing").count():
            break
        pg.wait_for_timeout(300)
    pg.wait_for_timeout(800)


def smooth_scroll(pg: Page, selector: str, to: str | int, ms: int = 1200) -> None:
    pg.evaluate(
        """([sel, to, ms]) => new Promise((done) => {
             const el = document.querySelector(sel); const start = el.scrollTop;
             const end = to === 'bottom' ? el.scrollHeight : (typeof to === 'number' ? to : document.querySelector(to).offsetTop - 24);
             const t0 = performance.now();
             const step = (t) => { const k = Math.min(1, (t - t0) / ms); el.scrollTop = start + (end - start) * (1 - Math.pow(1 - k, 3)); k < 1 ? requestAnimationFrame(step) : done(); };
             requestAnimationFrame(step);
           })""",
        [selector, to, ms],
    )


def run(url: str) -> Path:
    tmp = OUT / ".build" / "video"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp), record_video_size={"width": W, "height": H})
        ctx.add_cookies([{"name": "wa_lang", "value": "en", "url": url}])
        pg = ctx.new_page()
        pg.goto(f"{url}/?demo")
        pg.wait_for_timeout(1500)

        card(pg, "Keel", ["An AI wealth advisor that stress-tests the investor, not just the portfolio.",
                          "FinTechathon 2026 · International Track · Topic B: Wealth Advisory Agent"], 5000)
        cap(pg, "Keel runs a professional advisory workflow: fact-find, risk profile, portfolio, rehearsal, goal, and a client-confirmed trade.", 5200)

        # 1. dialogue with PII masking
        cap(pg, "The client can simply talk to the advisor.", 2600)
        chat(pg, "Hi, I'm 34 and want to invest 200,000 for my daughter's university in 8 years. My passport is E12345678 if you need it.")
        caption_on(pg, "The passport number was masked before the message reached the AI model.")
        pg.wait_for_timeout(5200)
        caption_off(pg)

        # 2. risk profile
        cap(pg, "Or fill in eight short questions. Chat and form update the same client file.", 3800)
        pg.fill("#amount", "200000")
        pg.fill("#age", "34")
        for fs in pg.locator("fieldset.q").all():
            n = fs.locator("input").count()
            fs.locator("input").nth(n - 1).check()
            pg.wait_for_timeout(260)
        pg.click("#assess")
        pg.wait_for_timeout(1200)
        cap(pg, "Risk class is the lower of loss capacity and risk tolerance, scored by fixed rules, not by the AI.", 5200)
        smooth_scroll(pg, "#panel", "bottom", 1400)
        cap(pg, "Every answer that shaped the class is listed in plain words.", 3600)

        # 3. portfolio with provenance
        pg.click("#toPortfolio")
        pg.wait_for_timeout(1800)
        cap(pg, "A portfolio of 24 real Chinese public funds, limited to products at or below the client's risk level.", 5000)
        pg.locator(".kpi .num").first.click()
        caption_on(pg, "Tap any number: it shows the function that computed it and its audit record. The AI never invents a figure.")
        pg.wait_for_timeout(5600)
        pg.keyboard.press("Escape")
        caption_off(pg)
        smooth_scroll(pg, "#panel", 520, 1000)
        pg.locator("[data-why]").first.click()
        cap(pg, "Every holding explains why it was chosen.", 3400)

        # 4. an unsuitable request in chat
        chat(pg, "Just put everything into the Nasdaq fund. I want a guaranteed 20% a year.")
        caption_on(pg, "Unsafe requests are declined: no guarantees, no concentration above the client's suitability.")
        pg.wait_for_timeout(6000)
        caption_off(pg)

        # 5. crash rehearsal
        pg.click("button[data-step='rehearse']")
        pg.wait_for_timeout(1200)
        cap(pg, "Our key idea, Crash Rehearsal: before any money moves, the client lives through 2008 with this exact portfolio.", 5600)
        pg.click("#startRehearsal")
        pg.wait_for_timeout(600)
        caption_on(pg, "Real monthly market data from October 2007, with the headlines of the time.")
        for _ in range(200):
            try:
                if float(pg.inner_text("#thDd").split("−")[-1].rstrip("%")) > 9:
                    break
            except ValueError:
                pass
            pg.wait_for_timeout(150)
        caption_on(pg, "The Sell button always shows the loss it would lock in.")
        for _ in range(200):
            try:
                if float(pg.inner_text("#thDd").split("−")[-1].rstrip("%")) > 15:
                    break
            except ValueError:
                pass
            pg.wait_for_timeout(150)
        pg.wait_for_timeout(900)
        caption_off(pg)
        pg.click("#thSell")
        pg.wait_for_timeout(2600)
        smooth_scroll(pg, "#panel", "#rehearsalResult", 900)
        cap(pg, "The client sold near the bottom. Holding would have recovered; selling locked in the loss.", 5000)
        cap(pg, "Revealed behaviour lowers the risk class. It can never raise it.", 4200)
        pg.click("#rebuildAtNew")
        pg.wait_for_timeout(1800)
        cap(pg, "The portfolio is rebuilt at the lower class, a plan this client can actually stay with.", 4400)

        # 6. goal
        pg.click("button[data-step='goal']")
        pg.wait_for_timeout(2200)
        cap(pg, "Goal planning: 5,000 simulated futures and the chance of reaching the target. Same inputs, same answer.", 5400)

        # 7. invest
        pg.click("button[data-step='execute']")
        pg.wait_for_timeout(1400)
        cap(pg, "Only the client can move money. First, read and sign the risk disclosure.", 4000)
        pg.check("#accept")
        pg.click("#signName")
        pg.keyboard.type("Alex Morgan", delay=60)
        pg.wait_for_timeout(600)
        pg.click("#signBtn")
        pg.wait_for_timeout(2600)
        cap(pg, "Higher-risk funds wait 24 hours in a cooling-off period, as the rules require.", 4400)
        caption_on(pg, "Hold to confirm. This issues a one-time token the AI model can never obtain.")
        box = pg.locator("#hold").bounding_box()
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        pg.wait_for_timeout(700)
        pg.mouse.down()
        pg.wait_for_timeout(1900)
        pg.mouse.up()
        caption_on(pg, "Five seconds to undo, then the orders go to the simulated broker.")
        pg.wait_for_timeout(6800)
        smooth_scroll(pg, "#panel", "#printer", 900)
        caption_on(pg, "The trade confirmation carries the audit-record hash, anchored on WeBank's FISCO BCOS chain.")
        pg.wait_for_timeout(6500)
        caption_off(pg)

        # 8. audit log and on-chain verification
        pg.click("#auditPill")
        pg.wait_for_timeout(1500)
        cap(pg, "Every decision is in a hash-chained audit log: guard checks, model calls, tool calls, consent and orders.", 5200)
        verify = pg.locator("[data-verify]").first
        if verify.count():
            verify.click()
            pg.wait_for_timeout(2500)
            cap(pg, "Verify recomputes the log and checks it against the smart contract on chain.", 4600)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(600)

        # 9. advice report
        pg.goto(f"{url}/report")
        pg.wait_for_timeout(1500)
        cap(pg, "The Advice Report: a fingerprinted suitability record the client can keep.", 4400)
        smooth_scroll(pg, "html", "bottom", 2600)
        pg.wait_for_timeout(600)

        card(pg, "Keel", ["The model talks. Code decides. The client confirms. The chain remembers.",
                          "65/65 red-team cases passed · 30/30 client journeys completed on the live model · English and 中文"], 6000)
        video = pg.video.path()
        ctx.close()
        browser.close()

    dest = OUT / "Keel_Demo.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)], check=True)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    dest = run(parser.parse_args().url.rstrip("/"))
    print(f"wrote {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
