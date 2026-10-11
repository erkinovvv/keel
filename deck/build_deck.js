// Builds deck/Lucid_FinTechathon_2026.pptx — the ≤10-minute pitch for Topic B.
//   cd deck && node build_deck.js
const path = require("path");
const pptxgen = require("pptxgenjs");

const SKILL_THEME = path.join(__dirname, "apply_theme.js");  // copied from the pptx skill
const IMG = (name) => path.join(__dirname, "..", "docs", "img", name);
const OUT = path.join(__dirname, "Lucid_FinTechathon_2026.pptx");

const THEME = {
  name: "Lucid",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "14211F", lt1: "FFFFFF", dk2: "07110F", lt2: "F3F6F5",
    accent1: "17695A", accent2: "FF6B5E", accent3: "2A78D6", accent4: "EDA100", accent5: "4A5B57", accent6: "8FD8C5",
    hlink: "17695A", folHlink: "0F4D42",
  },
};
const HEX = THEME.colors;
const NUMBERS = {
  journeys: "[__ / 30]",  // filled after the full live run
  redteam: "57 / 57",
  tests: "89",
  backtest: "5 / 5",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "Lucid — the AI wealth advisor that proves its advice";
pres.author = "[Name 1], [Name 2]";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333, M = 0.6;
const FOOTER = "Lucid · FinTechathon 2026 · Topic B";

pres.defineSlideMaster({
  title: "LIGHT_CONTENT",
  background: { color: C.background2 },
  objects: [
    { text: { text: FOOTER, options: { x: M, y: 7.0, w: 8, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
    { placeholder: { options: { name: "title", type: "title", x: M, y: 0.45, w: W - 2 * M, h: 0.9, fontFace: THEME.headFontFace, fontSize: 34, color: C.text1, valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: W - M - 0.5, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text2 },
  objects: [],
  slideNumber: { x: W - M - 0.5, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
});

const card = (slide, x, y, w, h, opts = {}) =>
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.12, fill: { color: opts.fill || C.background1 },
    line: { color: opts.line || "D9E2DF", width: 1 }, objectName: opts.name || "card",
  });
const text = (slide, value, opts) => slide.addText(value, { isTextBox: true, margin: 0, valign: "top", ...opts });

// ------------------------------------------------------------------ 1 cover
pres.addSection({ title: "Why advice cannot be checked" });
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Why advice cannot be checked" });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: M, y: 0.6, w: 0.45, h: 0.45, rectRadius: 0.1, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: "logo" });
  text(s, "Lucid", { x: M + 0.6, y: 0.62, w: 3, h: 0.45, fontSize: 22, bold: true, color: C.background1, valign: "middle" });
  text(s, "The AI wealth advisor that proves its advice", { x: M, y: 2.2, w: 11, h: 2.0, fontFace: THEME.headFontFace, fontSize: 54, color: C.background1, valign: "bottom" });
  text(s, "A licensed advisor's workflow, a crash rehearsal for the client, and an audit trail anchored on WeBank's FISCO BCOS.", { x: M, y: 4.4, w: 10, h: 1.0, fontSize: 20, color: "BFD0CC" });
  text(s, "FinTechathon 2026 · International Track · Topic B: Wealth Advisory Agent\n[Name 1], [Name 2] · Westminster International University in Tashkent", { x: M, y: 6.2, w: 11, h: 0.7, fontSize: 14, color: "BFD0CC" });
  s.addNotes("Hello, we are [names] from Westminster International University in Tashkent. Our project is Lucid, a wealth-advisory agent for Topic B. In one sentence: it is the AI wealth advisor that proves its advice. In the next nine minutes we show what that means and why it matters to a bank like WeBank.");
}

// ------------------------------------------------------------------ 2 problem
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Why advice cannot be checked" });
  s.addText("Wealth advice today cannot be checked", { placeholder: "title" });
  const items = [
    ["Questionnaires", "Clients tick the answers that unlock the product they want", "Then they sell at the bottom of the first crash, lose money and complain of mis-selling."],
    ["AI advisors", "Language models invent figures and can be talked into anything", "A confident wrong return estimate is a compliance incident, not a typo."],
    ["“Explainable”", "Every product claims it. Nobody can verify it afterwards.", "Regulators, auditors and clients need evidence, not a promise."],
  ];
  const cw = (W - 2 * M - 2 * 0.35) / 3;
  items.forEach(([label, head, body], i) => {
    const x = M + i * (cw + 0.35);
    card(s, x, 1.65, cw, 4.6, { name: `problem-${i + 1}` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.35, y: 1.95, w: 0.55, h: 0.55, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `problem-num-${i + 1}` });
    text(s, String(i + 1), { x: x + 0.35, y: 1.95, w: 0.55, h: 0.55, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle" });
    text(s, label, { x: x + 1.05, y: 1.98, w: cw - 1.3, h: 0.5, fontSize: 15, bold: true, color: C.accent1, valign: "middle" });
    text(s, head, { x: x + 0.35, y: 2.85, w: cw - 0.7, h: 1.6, fontFace: THEME.headFontFace, fontSize: 22, color: C.text1 });
    text(s, body, { x: x + 0.35, y: 4.55, w: cw - 0.7, h: 1.4, fontSize: 15, color: C.accent5 });
  });
  text(s, "Topic B asks for compliant and explainable asset-allocation advice. We took both words literally.", { x: M, y: 6.45, w: W - 2 * M, h: 0.4, fontSize: 15, italic: true, color: C.accent5 });
  s.addNotes("Three problems. First, risk questionnaires are easy to game: clients pick the answers that unlock the product they want, then panic-sell in the first crash. Second, language-model advisors invent numbers and can be jailbroken. Third, everyone says explainable, but nobody can verify a recommendation after the fact. Topic B asks for compliant and explainable advice; we took both words literally.");
}

// ------------------------------------------------------------------ 3 workflow
pres.addSection({ title: "Lucid" });
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Lucid" });
  s.addText("A licensed advisor's workflow, in one conversation", { placeholder: "title" });
  const steps = [["Fact-find", "chat or form, EN / 中文"], ["Profile", "C1–C5, lower of capacity and tolerance"], ["Rehearse", "live through 2008 first"], ["Allocate", "real funds, a reason per holding"], ["Plan", "goal odds from 5,000 futures"], ["Stress", "against the client's own limit"], ["Execute", "signed, held, on-chain"]];
  const sw = (W - 2 * M - 6 * 0.15) / 7;
  steps.forEach(([head, body], i) => {
    const x = M + i * (sw + 0.15);
    const dark = head === "Rehearse";
    card(s, x, 1.55, sw, 1.75, { fill: dark ? C.text2 : C.background1, line: dark ? "07110F" : "D9E2DF", name: `step-${i + 1}` });
    text(s, String(i + 1), { x: x + 0.18, y: 1.68, w: 0.6, h: 0.4, fontSize: 20, bold: true, color: dark ? C.accent2 : C.accent1 });
    text(s, head, { x: x + 0.18, y: 2.1, w: sw - 0.3, h: 0.4, fontSize: 16, bold: true, color: dark ? C.background1 : C.text1 });
    text(s, body, { x: x + 0.18, y: 2.5, w: sw - 0.3, h: 0.75, fontSize: 11.5, color: dark ? "BFD0CC" : C.accent5 });
  });
  s.addImage({ path: IMG("portfolio.png"), x: M + 1.4, y: 3.55, w: 9.3, h: 3.3, sizing: { type: "cover", w: 9.3, h: 3.3 }, altText: "Lucid web app: recommended portfolio, every number linked to the function that computed it", objectName: "screenshot-portfolio" });
  s.addNotes("Lucid runs the same seven steps a licensed advisor follows: fact-find, risk profile, crash rehearsal, allocation, goal planning, stress test and execution. The client can do it in conversation, in English or Chinese, and the client file fills in live. Every underlined number opens its provenance: which function computed it and which audit record holds it.");
}

// ------------------------------------------------------------------ 4 statement
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Lucid" });
  text(s, [
    { text: "Every robo-advisor stress-tests the portfolio. ", options: { color: C.background1 } },
    { text: "We stress-test the investor.", options: { color: C.accent2 } },
  ], { x: M, y: 1.6, w: 11.5, h: 2.8, fontFace: THEME.headFontFace, fontSize: 48, valign: "bottom" });
  text(s, "Before any money moves, the client lives through 2008 with the exact portfolio we recommend, and can press Sell at any moment.", { x: M, y: 4.7, w: 10, h: 1.0, fontSize: 20, color: "BFD0CC" });
  s.addNotes("This is our core idea. Every robo-advisor stress-tests the portfolio. We stress-test the investor. Before any money moves, the client lives through 2008 with the exact portfolio we are about to recommend, month by month, and can press Sell at any moment.");
}

// ------------------------------------------------------------------ 5 crash rehearsal
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Lucid" });
  s.addText("Crash Rehearsal: what clients do, not what they say", { placeholder: "title" });
  s.addImage({ path: IMG("rehearsal.png"), x: M, y: 1.55, w: 6.6, h: 4.15, sizing: { type: "cover", w: 6.6, h: 4.15 }, altText: "Crash Rehearsal screen: the client's portfolio falling to 88,033 in September 2008 with the Lehman headline and a Sell everything button", objectName: "screenshot-rehearsal" });
  const rx = M + 7.0, rw = W - M - rx;
  const rows = [
    ["Real history", "Oct 2007 – Mar 2013, month by month. Kenneth R. French, FRED and World Bank data; the headlines of the time."],
    ["Revealed tolerance", "Where the client sells sets the class the behaviour supports: below 5% C1 … below 25% C4."],
    ["Only ever safer", "New class = lower of stated and revealed. Holding never raises it. Logged and on the client's report."],
  ];
  rows.forEach(([head, body], i) => {
    const y = 1.55 + i * 1.12;
    text(s, head, { x: rx, y, w: rw, h: 0.35, fontSize: 16, bold: true, color: C.accent1 });
    text(s, body, { x: rx, y: y + 0.36, w: rw, h: 0.7, fontSize: 13.5, color: C.text1 });
  });
  card(s, M, 5.95, W - 2 * M, 0.85, { fill: C.text2, line: "07110F", name: "rehearsal-example" });
  text(s, [
    { text: "Real session:  ", options: { bold: true, color: C.accent6 } },
    { text: "said “I would buy more”  ·  sold in Sept 2008 at −13.5%  ·  class C5 → C3  ·  ", options: { color: C.background1 } },
    { text: "cost of panic −42,329 on 100,000", options: { bold: true, color: C.accent2 } },
  ], { x: M + 0.3, y: 5.95, w: W - 2 * M - 0.6, h: 0.85, fontSize: 16, valign: "middle" });
  s.addNotes("Here is the rehearsal. The screen turns into a trading terminal; the client's own portfolio falls month by month on real data, the headlines of the time scroll by, and the Sell button pulses at the bottom. In our test, a client who said they would buy more in a crash sold in September 2008 at minus 13.5 percent. Holding would have ended at 130,715; selling ended at 88,386. The class drops from C5 to C3, and that is written to the audit log and to the client's report. Behaviour can only make the advice safer, never riskier.");
}

// ------------------------------------------------------------------ 6 proof
pres.addSection({ title: "Proof" });
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Proof" });
  s.addText("The model talks. Code decides.", { placeholder: "title" });
  const head = { bold: true, color: C.background1, fill: { color: C.accent1 }, fontSize: 14 };
  const rows = [
    [{ text: "Concern", options: head }, { text: "Owned by", options: head }, { text: "Why", options: head }],
    ["Conversation, explanations", "Language model (Groq)", "Language is what models are good at"],
    ["Risk class, weights, returns, fees, stress, goal odds", "Deterministic, tested Python", "Reproducible; no invented figures"],
    ["Suitability C ≥ R, liquidity, limits, cooling-off", "Server code", "Cannot be talked around"],
    ["Placing an order", "The client only, one-time token", "The model has no tool that can trade"],
    ["Record of what happened", "Hash-chained log on FISCO BCOS", "Tamper-evident, independently checkable"],
  ];
  s.addTable(rows, { x: M, y: 1.55, w: 7.6, colW: [2.8, 2.4, 2.4], fontSize: 13, color: C.text1, fill: { color: C.background1 }, border: { type: "solid", pt: 0.75, color: "D9E2DF" }, margin: 0.08, valign: "middle", rowH: 0.62, objectName: "boundary-table" });
  const px = M + 8.0, pw = W - M - px;
  card(s, px, 1.55, pw, 4.9, { name: "provenance-card" });
  text(s, "Every number shows its source", { x: px + 0.3, y: 1.8, w: pw - 0.6, h: 0.45, fontSize: 17, bold: true, color: C.accent1 });
  text(s, "Tap 7.39% → “Computed by allocation.build_allocation() · audit record 1d99…”.\n\nThe audit-chain head is written to an AuditAnchor smart contract on WeBank's FISCO BCOS after every trade; Verify recomputes the log and compares. Edit one record: ✗.\n\nThe client's Advice Report carries its own SHA-256 in the chain.", { x: px + 0.3, y: 2.35, w: pw - 0.6, h: 3.9, fontSize: 14, color: C.text1 });
  s.addNotes("Our design rule: the model talks, code decides. The language model handles conversation. Every figure, the risk class, suitability, limits and the order path live in deterministic server code the model cannot reach. Every number in the interface links to the function that computed it, and every decision goes into a hash-chained audit log whose head we write to a smart contract on WeBank's FISCO BCOS. Change one record and verification fails.");
}

// ------------------------------------------------------------------ 7 real products
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Proof" });
  s.addText("Advice on 24 real Chinese public funds", { placeholder: "title" });
  const facts = [
    ["Open data", "East Money / Tiantian Fund pages, the source the AkShare library uses"],
    ["Real risk levels", "Distributor labels 低风险 … 高风险 mapped to R1 … R5"],
    ["Real costs", "Management, custody and sales-service fees per fund"],
    ["Honest estimates", "10-year NAV volatility; returns shrunk halfway to an asset-class prior"],
  ];
  facts.forEach(([head, body], i) => {
    const y = 1.6 + i * 1.2;
    s.addShape(pres.shapes.OVAL, { x: M, y: y + 0.05, w: 0.32, h: 0.32, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `fact-dot-${i + 1}` });
    text(s, head, { x: M + 0.5, y, w: 5.2, h: 0.4, fontSize: 16, bold: true, color: C.text1 });
    text(s, body, { x: M + 0.5, y: y + 0.4, w: 5.2, h: 0.7, fontSize: 13.5, color: C.accent5 });
  });
  const head = { bold: true, color: C.background1, fill: { color: C.accent1 }, fontSize: 14, align: "center" };
  const ladder = [
    [{ text: "Class", options: head }, { text: "Expected return", options: head }, { text: "Volatility", options: head }, { text: "Worst historical loss", options: head }],
    ["C1 Conservative", "1.1%", "0.2%", "0.0%"],
    ["C2", "2.6%", "1.5%", "8.2%"],
    ["C3 Balanced", "3.2%", "2.8%", "10.0%"],
    ["C4", "7.4%", "8.4%", "21.3%"],
    ["C5 Aggressive", "8.2%", "10.0%", "24.5%"],
  ].map((row, r) => r === 0 ? row : row.map((v, c) => ({ text: v, options: { align: c === 0 ? "left" : "right" } })));
  s.addTable(ladder, { x: M + 6.1, y: 1.6, w: 6.03, colW: [1.83, 1.4, 1.2, 1.6], fontSize: 14, color: C.text1, fill: { color: C.background1 }, border: { type: "solid", pt: 0.75, color: "D9E2DF" }, margin: 0.08, rowH: 0.55, valign: "middle", objectName: "class-ladder" });
  text(s, "Model portfolios of 100,000 built from the real catalog, net of fees. Worst of the 2008, 2020 and 2022 shocks.", { x: M + 6.1, y: 5.05, w: 6.03, h: 0.7, fontSize: 12, color: C.accent5 });
  s.addNotes("We replaced a mock catalog with 24 real Chinese public mutual funds: money market including Yu'E Bao, bond and balanced funds, CSI 300 and 500, Hang Seng, S&P 500, Nasdaq-100, gold and US real estate, the kind of products WeBank distributes. Risk levels R1 to R5 come from the distributor labels, fees are the real fees, volatility is ten years of NAV history. The table shows the resulting ladder: from 1.1 percent for C1 to 8.2 percent for C5, each with its worst historical loss.");
}

// ------------------------------------------------------------------ 8 security
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Proof" });
  s.addText("Security enforced in code, not in prompts", { placeholder: "title" });
  const tiers = [["T0 Info", "education, product facts"], ["T1 Advise", "default: profile, portfolio, stress, goals"], ["T2 Propose", "draft orders after pre-trade checks"], ["T3 Execute", "only with the client's one-time token"]];
  tiers.forEach(([head, body], i) => {
    const y = 1.6 + i * 1.08;
    const strong = i === 3;
    card(s, M, y, 5.6, 0.88, { fill: strong ? C.accent1 : C.background1, line: strong ? "17695A" : "D9E2DF", name: `tier-${i}` });
    text(s, head, { x: M + 0.25, y, w: 1.6, h: 0.88, fontSize: 15, bold: true, color: strong ? C.background1 : C.accent1, valign: "middle" });
    text(s, body, { x: M + 1.9, y, w: 3.55, h: 0.88, fontSize: 13, color: strong ? C.background1 : C.text1, valign: "middle" });
  });
  text(s, "Signed risk disclosure → hold 1.5 s → 5 s undo. Tokens: hashed, bound to the exact order, single use, 5-minute expiry. Kill switch caps every session at T1.", { x: M, y: 5.95, w: 5.6, h: 0.9, fontSize: 12.5, color: C.accent5 });
  const bx = M + 6.1;
  text(s, NUMBERS.redteam, { x: bx, y: 1.5, w: 6, h: 1.1, fontFace: THEME.headFontFace, fontSize: 60, color: C.accent1 });
  text(s, "red-team attacks stopped, and 8 / 8 harmless requests answered normally", { x: bx, y: 2.6, w: 6, h: 0.5, fontSize: 15, color: C.text1 });
  const cats = ["Prompt injection, 10", "Chinese, Russian, Uzbek, Spanish, 5", "Obfuscated (base64, leetspeak), 4", "Role-play jailbreaks, 3", "Injection inside fund data, 5", "Personal data leaks, 10", "Unsafe claims and invented numbers, 6", "Suitability bypass, 4", "Execution without consent, 6", "Audit tampering and abuse, 4"];
  text(s, cats.map((c, i) => ({ text: c, options: { bullet: true, breakLine: i < cats.length - 1 } })), { x: bx, y: 3.3, w: 6, h: 3.3, fontSize: 13, color: C.text1, paraSpaceAfter: 4 });
  s.addNotes("Security is thirty percent of the score, so we enforce it in code. Four permission tiers; a session starts at Advise. Trading needs a signed risk disclosure, and every order needs a one-time token that only the person holding the confirm button receives; the model has no tool that can obtain it. Personal data is masked before any model call. Our red-team suite stops all 57 attacks, in five languages, while answering all 8 harmless control requests normally.");
}

// ------------------------------------------------------------------ 9 results
pres.addSection({ title: "Results and fit" });
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Results and fit" });
  s.addText("Measured, not claimed", { placeholder: "title" });
  const stats = [
    [NUMBERS.journeys, "client journeys completed end to end on a live model (30 personas, C1–C5, 1 in 5 in Chinese)"],
    [NUMBERS.redteam, "red-team attacks stopped across 12 categories"],
    [NUMBERS.tests, "automated tests, including a live FISCO BCOS round trip"],
    [NUMBERS.backtest, "model portfolios inside their volatility band, 2008–2026"],
  ];
  const tw = (W - 2 * M - 3 * 0.3) / 4;
  stats.forEach(([n, label], i) => {
    const x = M + i * (tw + 0.3);
    card(s, x, 1.6, tw, 2.6, { name: `stat-${i + 1}` });
    text(s, n, { x: x + 0.25, y: 1.8, w: tw - 0.5, h: 0.95, fontFace: THEME.headFontFace, fontSize: 40, color: C.accent1 });
    text(s, label, { x: x + 0.25, y: 2.8, w: tw - 0.5, h: 1.3, fontSize: 13, color: C.text1 });
  });
  card(s, M, 4.55, W - 2 * M, 1.95, { fill: C.text2, line: "07110F", name: "backtest-insight" });
  text(s, "What the backtest taught us", { x: M + 0.35, y: 4.75, w: 6, h: 0.4, fontSize: 15, bold: true, color: C.accent6 });
  text(s, "Every class kept its volatility target for 18 years, yet every class's worst fall was deeper than that number suggests: C5's 2008 drawdown was 34%. A volatility figure does not tell a client what 2008 feels like. That is why Lucid enforces the client's own loss limit and makes them rehearse the crash.", { x: M + 0.35, y: 5.2, w: W - 2 * M - 0.7, h: 1.2, fontSize: 15, color: C.background1 });
  s.addNotes("Numbers we measured. [x] of 30 scripted clients completed the whole journey on a live model. All 57 red-team attacks stopped. 89 automated tests. And a backtest from 2008 to 2026: every model portfolio stayed inside its volatility band, yet every one fell further than that number suggests; C5 lost 34 percent in 2008. That is exactly why we enforce the client's own loss limit and make them rehearse the crash.");
}

// ------------------------------------------------------------------ 10 architecture
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Results and fit" });
  s.addText("Architecture", { placeholder: "title" });
  const box = (x, y, w, h, title, body, opts = {}) => {
    card(s, x, y, w, h, { fill: opts.fill, line: opts.line, name: opts.name });
    text(s, title, { x: x + 0.2, y: y + 0.15, w: w - 0.4, h: 0.38, fontSize: 14, bold: true, color: opts.titleColor || C.accent1 });
    text(s, body, { x: x + 0.2, y: y + 0.55, w: w - 0.4, h: h - 0.65, fontSize: 11.5, color: opts.bodyColor || C.text1 });
  };
  box(M, 1.6, 2.6, 1.6, "Web app", "Chat + client file, EN / 中文, provenance on every number", { name: "arch-ui" });
  box(M + 3.1, 1.6, 3.4, 1.6, "Advisor session", "Input guard (PII, injection) → agent loop with stage-aware tools → output guard (grounded numbers)", { name: "arch-session" });
  box(M + 7.0, 1.6, 2.4, 1.6, "Groq LLMs", "gpt-oss-120b, fallbacks, Prompt Guard; replay offline", { name: "arch-llm" });
  box(M + 3.1, 3.75, 3.4, 1.9, "Deterministic engine", "Profiling · Crash Rehearsal · allocation (Ledoit-Wolf, stress limit) · stress · goal Monte Carlo", { name: "arch-engine" });
  box(M + 7.0, 3.75, 2.4, 1.9, "Real data", "24 Chinese funds · French · FRED · World Bank", { name: "arch-data" });
  box(M, 3.75, 2.6, 1.9, "Execution", "Tiers T0–T3, one-time tokens, simulated account, T+2", { name: "arch-exec" });
  box(M + 9.9, 1.6, 2.23, 4.05, "FISCO BCOS", "AuditAnchor contract on a 4-node consortium chain. Hash-chained audit log; Verify recomputes and compares.", { fill: C.text2, line: "07110F", titleColor: C.accent6, bodyColor: C.background1, name: "arch-chain" });
  const arrow = (x, y, w) => s.addShape(pres.shapes.RIGHT_ARROW, { x, y, w, h: 0.3, fill: { color: C.accent5 }, line: { color: C.accent5 }, objectName: "arch-arrow" });
  arrow(M + 2.65, 2.25, 0.4);
  arrow(M + 6.55, 2.25, 0.4);
  arrow(M + 9.45, 3.5, 0.4);
  s.addShape(pres.shapes.DOWN_ARROW, { x: M + 4.6, y: 3.25, w: 0.3, h: 0.45, fill: { color: C.accent5 }, line: { color: C.accent5 }, objectName: "arch-down" });
  text(s, "Python 3.12 · FastAPI · NumPy · web3.py + Solidity · plain HTML/CSS/JS · one command: uv run wealth-advisor-ui", { x: M, y: 6.0, w: W - 2 * M, h: 0.4, fontSize: 12.5, color: C.accent5 });
  s.addNotes("The architecture in one picture. The web app talks to an advisor session. Every message passes an input guard that masks personal data and catches injection, then a bounded agent loop that only sees the tools valid for the current stage, then an output guard that refuses numbers no tool produced. The tools call a deterministic engine on real data. Execution sits behind permission tiers and one-time tokens. Everything is written to a hash-chained audit log anchored on FISCO BCOS.");
}

// ------------------------------------------------------------------ 11 WeBank fit
{
  const s = pres.addSlide({ masterName: "LIGHT_CONTENT", sectionTitle: "Results and fit" });
  s.addText("Built for a bank like WeBank", { placeholder: "title" });
  const items = [
    ["FISCO BCOS", "Built", "Advisory records anchored on WeBank's consortium chain. In production, nodes run by the bank, an auditor and the regulator."],
    ["FATE federated learning", "Next", "Crash Rehearsal creates a new signal: revealed risk tolerance. Banks could learn to predict it from questionnaires with FATE, without pooling client data."],
    ["Fund distribution", "Built", "Real public funds with distributor risk levels, the products a digital bank already sells."],
    ["Shenzhen, APEC 2026", "Built", "Bilingual English / 简体中文 interface; clients from across the region."],
  ];
  const cw = (W - 2 * M - 0.3) / 2;
  items.forEach(([head, status, body], i) => {
    const x = M + (i % 2) * (cw + 0.3), y = 1.6 + Math.floor(i / 2) * 2.45;
    card(s, x, y, cw, 2.2, { name: `fit-${i + 1}` });
    text(s, head, { x: x + 0.3, y: y + 0.25, w: cw - 2, h: 0.45, fontSize: 18, bold: true, color: C.text1 });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + cw - 1.3, y: y + 0.27, w: 1.0, h: 0.4, rectRadius: 0.2, fill: { color: status === "Built" ? C.accent1 : C.background2 }, line: { color: status === "Built" ? "17695A" : "D9E2DF" }, objectName: `fit-status-${i + 1}` });
    text(s, status, { x: x + cw - 1.3, y: y + 0.27, w: 1.0, h: 0.4, fontSize: 12, bold: true, color: status === "Built" ? C.background1 : C.accent5, align: "center", valign: "middle" });
    text(s, body, { x: x + 0.3, y: y + 0.85, w: cw - 0.6, h: 1.2, fontSize: 14, color: C.accent5 });
  });
  s.addNotes("Why this fits WeBank. The audit records already go to FISCO BCOS, the chain WeBank built. Next, FATE: Crash Rehearsal produces a new signal, revealed risk tolerance, and banks could learn to predict it from questionnaire answers with federated learning without pooling client data. The products are real public funds like those a digital bank distributes, and the interface is bilingual for Shenzhen and the APEC region.");
}

// ------------------------------------------------------------------ 12 close
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Results and fit" });
  text(s, "Advice you can prove.", { x: M, y: 2.0, w: 11, h: 1.4, fontFace: THEME.headFontFace, fontSize: 60, color: C.background1, valign: "bottom" });
  text(s, "Rehearse the crash. Ground every number. Let only the client move money. Anchor the record on chain.", { x: M, y: 3.6, w: 10.5, h: 1.0, fontSize: 20, color: "BFD0CC" });
  text(s, "Code and documentation: github.com/[account]/[repository]  ·  Demo video: [link]\n[Name 1], [Name 2] · Westminster International University in Tashkent", { x: M, y: 5.8, w: 11.5, h: 0.8, fontSize: 14, color: "BFD0CC" });
  s.addNotes("Lucid: advice you can prove. We rehearse the crash before the client invests, every number is grounded in audited code, only the client can move money, and the record lives on chain. Thank you; we are happy to take questions and to show the live demo.");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  if (SKILL_THEME) {
    const { applyTheme } = require(SKILL_THEME);
    await applyTheme(OUT, THEME);
  }
  console.log("wrote", OUT);
})();
