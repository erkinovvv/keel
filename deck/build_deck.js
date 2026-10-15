// Builds submission/Keel_FinTechathon_2026_10min_Final.pptx, the 10-minute pitch for Topic B.
//   cd deck && node build_deck.js
// Figures come from the repository: evals/journeys/REPORT.md, evals/redteam/REPORT.md, the pytest count,
// docs/ALGORITHM.md (backtest) and evidence/02-crash-rehearsal (rehearsal example).
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("./apply_theme.js");  // copied from the pptx skill

const IMG = (name) => path.join(__dirname, "..", "docs", "img", name);
const ASSET = (name) => path.join(__dirname, "assets", name);
const OUT = path.join(__dirname, "..", "submission", "Keel_FinTechathon_2026_10min_Final.pptx");

// Keel design system: ink and canvas, navy for data, brass for the one thing that matters on a slide.
const THEME = {
  name: "Keel",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: "0F1B26", lt1: "FFFFFF", dk2: "0A1016", lt2: "F5F6F7",
    accent1: "23476B", accent2: "8A6420", accent3: "0F9A8C", accent4: "C9623A", accent5: "5A6773", accent6: "C9A45C",
    hlink: "23476B", folHlink: "6E4F16",
  },
};
const RULE = "DDE2E7", RULE_STRONG = "C5CDD5", SEA_DIM = "A6B1BC", SEA_RULE = "2E3F4E";
const NUMBERS = {
  journeys: "30 / 30",   // evals/journeys/REPORT.md
  redteam: "57 / 57",    // evals/redteam/REPORT.md
  benign: "8 / 8",
  tests: "156",          // LLM_MODE=replay LIVE_MARKET=0 uv run pytest -q
  backtest: "5 / 5",     // docs/ALGORITHM.md section 6
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "Keel: an AI wealth advisor";
pres.author = "Team Keel";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333, M = 0.7;
const FOOTER = "Keel   FinTechathon 2026, International Track, Topic B";

pres.defineSlideMaster({
  title: "LIGHT",
  background: { color: C.background2 },
  objects: [
    { line: { x: M, y: 6.95, w: W - 2 * M, h: 0, line: { color: RULE, width: 0.75 } } },
    { text: { text: FOOTER, options: { x: M, y: 7.02, w: 8, h: 0.28, fontSize: 9.5, color: C.accent5, margin: 0 } } },
    { placeholder: { options: { name: "title", type: "title", x: M, y: 0.5, w: W - 2 * M, h: 0.8, fontFace: THEME.headFontFace, fontSize: 30, bold: true, color: C.text1, align: "left", valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: W - M - 0.6, y: 7.02, w: 0.6, h: 0.28, fontSize: 9.5, color: C.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text2 },
  objects: [],
  slideNumber: { x: W - M - 0.6, y: 7.02, w: 0.6, h: 0.28, fontSize: 9.5, color: SEA_DIM, align: "right" },
});

const text = (slide, value, opts) => slide.addText(value, { isTextBox: true, margin: 0, valign: "top", fontFace: THEME.bodyFontFace, ...opts });
const rule = (slide, x, y, w, color = RULE, name = "rule") => slide.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color, width: 0.75 }, objectName: name });
const vrule = (slide, x, y, h, color = RULE, name = "vrule") => slide.addShape(pres.shapes.LINE, { x, y, w: 0, h, line: { color, width: 0.75 }, objectName: name });
const shot = (slide, file, x, y, w, alt, name) => {
  const h = w * (1800 / 2880);
  slide.addImage({ path: IMG(file), x, y, w, h, altText: alt, objectName: name });
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { type: "none" }, line: { color: RULE_STRONG, width: 0.75 }, objectName: `${name}-frame` });
  return h;
};

// ------------------------------------------------------------------ 1 cover
pres.addSection({ title: "The problem" });
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "The problem" });
  s.addImage({ path: ASSET("mark_light.png"), x: M, y: 0.7, w: 0.5, h: 0.5, altText: "Keel logo", objectName: "logo" });
  text(s, "Keel", { x: M + 0.68, y: 0.7, w: 3, h: 0.5, fontSize: 22, bold: true, color: C.background1, valign: "middle" });
  text(s, "An AI wealth advisor that lets clients live through a crash before they invest, and can prove every number it shows.", { x: M, y: 2.1, w: 11.2, h: 2.4, fontSize: 44, bold: true, color: C.background1, valign: "bottom", lineSpacingMultiple: 0.95 });
  rule(s, M, 5.75, W - 2 * M, SEA_RULE, "cover-rule");
  text(s, "2026 Shenzhen International FinTech Competition, International Track, Topic B: Wealth Advisory Agent\nTeam Keel   Westminster International University in Tashkent", { x: M, y: 5.95, w: 11.5, h: 0.75, fontSize: 14, color: SEA_DIM, lineSpacingMultiple: 1.2 });
  s.addNotes("Hello, we are Team Keel from Westminster International University in Tashkent. Our project for Topic B is Keel, an AI wealth advisor for Chinese retail investors. Before a client invests, Keel lets them live through a market crash with the exact portfolio it recommends. Every number can be traced to the code that computed it. Over the next ten minutes, we will show the client problem, the product journey and the controls that make the advice auditable. Our central idea is simple: simulate the decision before money moves, and keep the model outside the financial decision path.");
}

// ------------------------------------------------------------------ 2 problem
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "The problem" });
  s.addText("Advice fails at the moment it matters", { placeholder: "title" });
  const items = [
    ["Questionnaires", "Clients pick the answers that unlock the product they want.", "Then they sell at the bottom of the first crash and lose money they would have kept by holding."],
    ["AI advisors", "Language models invent figures and can be talked into anything.", "One confident but wrong return estimate is a compliance incident, not a typo."],
    ["Explainability", "Every product claims it. Nobody can check it afterwards.", "Regulators, auditors and clients need evidence they can verify themselves."],
  ];
  const cw = (W - 2 * M) / 3;
  items.forEach(([label, head, body], i) => {
    const x = M + i * cw;
    if (i) vrule(s, x, 1.75, 4.3, RULE, `problem-divider-${i}`);
    const px = x + (i ? 0.4 : 0), pw = cw - 0.8;
    text(s, label, { x: px, y: 1.75, w: pw, h: 0.4, fontSize: 14, bold: true, color: C.accent2 });
    text(s, head, { x: px, y: 2.3, w: pw, h: 1.9, fontSize: 24, bold: true, color: C.text1, lineSpacingMultiple: 1.0 });
    text(s, body, { x: px, y: 4.35, w: pw, h: 1.6, fontSize: 16, color: C.accent5 });
  });
  rule(s, M, 6.25, W - 2 * M, RULE_STRONG, "problem-rule");
  text(s, "Topic B asks for compliant and explainable allocation advice. Keel makes both claims checkable.", { x: M, y: 6.38, w: W - 2 * M, h: 0.4, fontSize: 16, color: C.text1 });
  s.addNotes("Three problems. First, risk questionnaires are easy to game: clients choose answers that unlock the product they want, then may panic-sell in the first crash. Second, language-model advisors can invent numbers or follow instructions that conflict with policy. Third, everyone says their advice is explainable, but clients and auditors need to verify an actual recommendation afterwards. In China, a fluent interface can build trust quickly, so controls must keep pace. Topic B asks for compliant, explainable allocation advice. Keel builds both into the client journey: suitability checks run in code, and the evidence stays visible.");
}

// ------------------------------------------------------------------ 3 statement
pres.addSection({ title: "Keel" });
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Keel" });
  text(s, [
    { text: "What clients say about risk ", options: { color: C.background1 } },
    { text: "is not what they do in a crash.", options: { color: C.accent6 } },
  ], { x: M, y: 1.4, w: 11.6, h: 2.9, fontSize: 52, bold: true, valign: "bottom", lineSpacingMultiple: 0.95 });
  text(s, "So before any money moves, Keel has the client live through 2008 with the exact portfolio it recommends, and lets them press Sell at any moment.", { x: M, y: 4.75, w: 10.6, h: 1.1, fontSize: 21, color: SEA_DIM });
  s.addNotes("This is our core insight. What clients say about risk in a questionnaire is not always what they do in a crash. Before any money moves, Keel lets the client live through the 2008 crisis with the exact portfolio it is considering, month by month, and shows the loss behind the Sell button. It spans October 2007 to March 2013. It is a historical rehearsal, not a prediction of the next market decline. We use it to test the client’s response to risk, then let that evidence make the advice more cautious.");
}

// ------------------------------------------------------------------ 4 workflow
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Keel" });
  s.addText("A licensed advisor's workflow, in five steps", { placeholder: "title" });
  const steps = [["Risk profile", "C1 to C5, the lower of loss capacity and risk tolerance"], ["Portfolio", "real funds, a reason for every holding"], ["Rehearse", "live through 2008 before investing"], ["Goal", "the chance of reaching it, from 5,000 futures"], ["Invest", "signed, held to confirm, recorded on chain"]];
  const sw = (W - 2 * M) / 5;
  rule(s, M, 1.55, W - 2 * M, RULE_STRONG, "steps-top");
  steps.forEach(([head, body], i) => {
    const x = M + i * sw;
    if (i) vrule(s, x, 1.55, 1.25, RULE, `step-divider-${i}`);
    const key = head === "Rehearse";
    const px = x + (i ? 0.2 : 0);
    text(s, String(i + 1), { x: px, y: 1.72, w: 0.5, h: 0.35, fontSize: 14, bold: true, color: key ? C.accent2 : C.accent5 });
    text(s, head, { x: px + 0.35, y: 1.72, w: sw - 0.6, h: 0.35, fontSize: 16, bold: true, color: key ? C.accent2 : C.text1 });
    text(s, body, { x: px, y: 2.15, w: sw - 0.35, h: 0.6, fontSize: 12, color: C.accent5 });
  });
  rule(s, M, 2.8, W - 2 * M, RULE, "steps-bottom");
  const h = shot(s, "portfolio.png", M, 3.1, 6.0, "Keel web app: recommended portfolio of real Chinese funds; a popover shows the function that computed a figure", "screenshot-portfolio");
  const rx = M + 6.5, rw = W - M - rx;
  const notes = [
    ["Chat or form", "The client can talk in English or 中文, or answer eight short questions. Both fill the same client file."],
    ["Every number has a source", "Tap any figure to see the function that computed it and its audit record."],
    ["Two optional tools", "Compare products and run crisis tests when needed."],
  ];
  notes.forEach(([head, body], i) => {
    const y = 3.1 + i * (h / 3);
    if (i) rule(s, rx, y - 0.12, rw, RULE, `workflow-note-rule-${i}`);
    text(s, head, { x: rx, y, w: rw, h: 0.35, fontSize: 15, bold: true, color: C.text1 });
    text(s, body, { x: rx, y: y + 0.38, w: rw, h: 0.7, fontSize: 13, color: C.accent5 });
  });
  s.addNotes("Keel follows five steps: risk profile, portfolio, rehearsal, goal planning and investing. The profile separates loss capacity from risk tolerance, and the lower class governs suitability. The client can answer questions in English or Chinese, or use the same short form; both update one client file. Keel compares eligible products, builds a portfolio, and lets the client test a historical crisis or a savings goal. A simulated order is the final step, after disclosure and client confirmation. Comparison and crisis tools are optional. Every underlined number opens its function and audit record.");
}

// ------------------------------------------------------------------ 5 crash rehearsal
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Keel" });
  s.addText("Crash Rehearsal: what clients do, not what they say", { placeholder: "title" });
  const h = shot(s, "rehearsal.png", M, 1.55, 6.6, "Crash Rehearsal: the client's portfolio replayed through 2008 with headlines and a Sell everything button that shows the loss it would lock in", "screenshot-rehearsal");
  const rx = M + 7.1, rw = W - M - rx;
  const rows = [
    ["Real history", "October 2007 to March 2013, month by month, on Kenneth R. French, FRED and World Bank data, with the headlines of the time."],
    ["Revealed tolerance", "Where the client sells sets the risk class their behaviour supports."],
    ["Only ever safer", "The new class is the lower of stated and revealed. Holding never raises it. The result is logged and printed on the client's report."],
  ];
  rows.forEach(([head, body], i) => {
    const y = 1.55 + i * (h / 3);
    if (i) rule(s, rx, y - 0.12, rw, RULE, `rehearsal-rule-${i}`);
    text(s, head, { x: rx, y, w: rw, h: 0.35, fontSize: 15, bold: true, color: C.text1 });
    text(s, body, { x: rx, y: y + 0.38, w: rw, h: 0.9, fontSize: 13, color: C.accent5 });
  });
  rule(s, M, 5.95, W - 2 * M, RULE_STRONG, "rehearsal-example-rule");
  text(s, [
    { text: "Evidence session 02:  ", options: { bold: true, color: C.text1 } },
    { text: "the client said they would buy more in a fall, then sold in September 2008, 12.5% below the peak. Holding would have ended at 133,266 on 100,000; selling ended at 89,601. Class lowered from C5 to C3, and the old C5 portfolio was refused.", options: { color: C.accent5 } },
  ], { x: M, y: 6.1, w: W - 2 * M, h: 0.75, fontSize: 14 });
  s.addNotes("Here is the rehearsal. The screen goes dark; the client’s proposed portfolio moves month by month on historical market data, and headlines from the period provide context. The Sell button shows the loss the simulated sale would lock in. In one recorded evidence session, a client who said they would buy more in a fall sold in September 2008, 12.5 percent below the peak. Holding would have ended at 133,266 on 100,000; selling ended at 89,601. Keel lowered the class from C5 to C3 and refused the old C5 portfolio. The client can rebuild within that class. This is a behavioral signal, not a penalty: it can reduce the risk Keel recommends, never raise it. The rehearsal only changes a simulated account.");
}

// ------------------------------------------------------------------ 6 model talks, code decides
pres.addSection({ title: "Proof" });
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Proof" });
  s.addText("The model talks. Code decides.", { placeholder: "title" });
  const head = { bold: true, color: C.accent5, fontSize: 12, border: [{ type: "none" }, { type: "none" }, { pt: 1, color: RULE_STRONG }, { type: "none" }] };
  const cell = (t, extra = {}) => ({ text: t, options: { border: [{ type: "none" }, { type: "none" }, { pt: 0.75, color: RULE }, { type: "none" }], ...extra } });
  const rows = [
    [{ text: "Concern", options: head }, { text: "Owned by", options: head }, { text: "Why", options: head }],
    [cell("Conversation and explanations"), cell("Language model (Groq)"), cell("Language is what models do well")],
    [cell("Risk class, weights, returns, fees, stress losses, goal odds"), cell("Deterministic, tested Python"), cell("Reproducible, no invented figures")],
    [cell("Suitability, liquidity, limits, cooling-off"), cell("Server code"), cell("Cannot be talked around")],
    [cell("Placing an order"), cell("The client only, with a one-time token", { bold: true, color: C.accent2 }), cell("The model has no tool that can trade")],
    [cell("Record of what happened"), cell("Hash-chained log, anchored on FISCO BCOS"), cell("Tamper-evident, checkable by anyone")],
  ];
  s.addTable(rows, { x: M, y: 1.55, w: 7.7, colW: [2.9, 2.5, 2.3], fontSize: 13, color: C.text1, fontFace: THEME.bodyFontFace, margin: [0.06, 0.12, 0.06, 0], valign: "middle", rowH: 0.62, objectName: "boundary-table" });
  const px = M + 8.3, pw = W - M - px;
  vrule(s, px - 0.3, 1.55, 4.6, RULE, "proof-divider");
  const blocks = [
    ["Every number shows its source", "Tap 7.43% and Keel shows: computed by allocation.build_allocation(), audit record cfbe5d57."],
    ["No ungrounded figures", "An output guard checks each number in a reply against this session's tool results, and blocks promises such as \"guaranteed\"."],
    ["Verifiable afterwards", "The audit-log head is written to a smart contract on WeBank's FISCO BCOS. Verify recomputes the log; one edited record fails."],
  ];
  blocks.forEach(([h2, body], i) => {
    const y = 1.55 + i * 1.55;
    if (i) rule(s, px, y - 0.15, pw, RULE, `proof-rule-${i}`);
    text(s, h2, { x: px, y, w: pw, h: 0.35, fontSize: 15, bold: true, color: C.text1 });
    text(s, body, { x: px, y: y + 0.4, w: pw, h: 1.0, fontSize: 13, color: C.accent5 });
  });
  s.addNotes("Our design rule is that the model talks and code decides. The language model asks questions and explains results; deterministic server code calculates every figure, assigns the risk class and checks suitability. The output guard compares every number in a reply with this turn’s tool results and blocks unsafe promises. The model has no execution tool and cannot create a confirmation token. Guards, model calls, tools and simulated orders enter a hash-chained log. We anchor its head on FISCO BCOS so reviewers can detect later changes.");
}

// ------------------------------------------------------------------ 7 real products
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Proof" });
  s.addText("Advice on 24 real Chinese public funds", { placeholder: "title" });
  const facts = [
    ["Public data", "Fund pages on East Money and Tiantian Fund, the source the open-source AkShare library uses."],
    ["Real risk levels", "Distributor labels 低风险 to 高风险, mapped to R1 to R5."],
    ["Real costs", "Management, custody and sales-service fees for every fund."],
    ["Honest estimates", "Ten years of NAV volatility; returns shrunk halfway to an asset-class prior."],
  ];
  facts.forEach(([head, body], i) => {
    const y = 1.55 + i * 1.18;
    if (i) rule(s, M, y - 0.14, 5.4, RULE, `fact-rule-${i}`);
    text(s, head, { x: M, y, w: 5.4, h: 0.35, fontSize: 15, bold: true, color: C.text1 });
    text(s, body, { x: M, y: y + 0.38, w: 5.4, h: 0.7, fontSize: 13, color: C.accent5 });
  });
  const hdr = (t, align) => ({ text: t, options: { bold: true, color: C.accent5, fontSize: 12, align, border: [{ type: "none" }, { type: "none" }, { pt: 1, color: RULE_STRONG }, { type: "none" }] } });
  const c = (t, align, extra = {}) => ({ text: t, options: { align, border: [{ type: "none" }, { type: "none" }, { pt: 0.75, color: RULE }, { type: "none" }], ...extra } });
  const ladder = [
    [hdr("Risk class", "left"), hdr("Expected return", "right"), hdr("Typical swing", "right"), hdr("Worst historical loss", "right")],
    ...[["C1 Conservative", "1.1%", "0.2%", "0.0%"], ["C2", "2.4%", "1.0%", "8.2%"], ["C3 Balanced", "2.6%", "1.1%", "10.0%"], ["C4", "7.1%", "8.2%", "21.3%"], ["C5 Aggressive", "8.0%", "9.9%", "24.5%"]]
      .map(([a, b, d, e]) => [c(a, "left"), c(b, "right", { color: C.accent1, bold: true }), c(d, "right"), c(e, "right")]),
  ];
  const tx = M + 6.2;
  s.addTable(ladder, { x: tx, y: 1.55, w: W - M - tx, colW: [2.0, 1.45, 1.35, 1.633], fontSize: 14, color: C.text1, fontFace: THEME.bodyFontFace, margin: [0.06, 0.1, 0.06, 0], rowH: 0.56, valign: "middle", objectName: "class-ladder" });
  text(s, "Model portfolios of 100,000 from the real catalog, after fees, before the client's own loss limit is applied. Worst of the 2008, 2020 and 2022 shocks.", { x: tx, y: 5.15, w: W - M - tx, h: 0.7, fontSize: 12, color: C.accent5 });
  s.addNotes("The catalog contains 24 real Chinese public mutual funds across money market, bond, index, QDII and gold categories. We use distributor risk labels, from R1 to R5, and the funds’ stated fees. A client can only receive recommendations at or below their investor class. The return and volatility figures are estimates from the available NAV history, with returns adjusted toward an asset-class prior; the fee is included in the displayed estimate. The table supports comparison, not a promise or forecast. Data have a collection date, and before real deployment the bank would need an operational freshness process and its own approved product universe.");
}

// ------------------------------------------------------------------ 8 security
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Proof" });
  s.addText("Security enforced in code, not in prompts", { placeholder: "title" });
  const tiers = [["T0 Info", "education and product facts"], ["T1 Advise", "the default: profile, portfolio, stress tests, goals"], ["T2 Propose", "draft orders after pre-trade checks"], ["T3 Execute", "only with the client's one-time token"]];
  rule(s, M, 1.55, 5.8, RULE_STRONG, "tiers-top");
  tiers.forEach(([head, body], i) => {
    const y = 1.55 + i * 0.85;
    const strong = i === 3;
    text(s, head, { x: M, y: y + 0.12, w: 1.6, h: 0.6, fontSize: 15, bold: true, color: strong ? C.accent2 : C.text1, valign: "middle" });
    text(s, body, { x: M + 1.7, y: y + 0.12, w: 4.1, h: 0.6, fontSize: 14, color: strong ? C.accent2 : C.accent5, valign: "middle" });
    rule(s, M, y + 0.85, 5.8, RULE, `tier-rule-${i}`);
  });
  text(s, "Trading needs a signed risk disclosure, a 1.5-second hold and a 5-second undo window. Tokens are hashed, bound to the exact order, single use and expire in five minutes. A kill switch caps every session at T1. Personal data is masked before any model call.", { x: M, y: 5.15, w: 5.8, h: 1.4, fontSize: 13, color: C.accent5 });
  const bx = M + 6.6, bw = W - M - bx;
  vrule(s, bx - 0.35, 1.55, 5.0, RULE, "security-divider");
  text(s, NUMBERS.redteam, { x: bx, y: 1.45, w: bw, h: 1.1, fontSize: 64, bold: true, color: C.accent1 });
  text(s, `red-team attacks stopped, and ${NUMBERS.benign} harmless requests still answered normally`, { x: bx, y: 2.6, w: bw, h: 0.6, fontSize: 15, color: C.text1 });
  const cats = ["Prompt injection (10)", "Injection in Chinese, Russian, Uzbek, Spanish (5)", "Obfuscated: base64, leetspeak, acrostic (4)", "Role-play jailbreaks (3)", "Injection hidden in fund data (5)", "Personal data leaks (10)", "Unsafe claims and invented numbers (6)", "Suitability bypass (4)", "Execution without consent (6)", "Audit tampering and abuse (4)"];
  text(s, cats.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < cats.length - 1 } })), { x: bx, y: 3.4, w: bw, h: 3.2, fontSize: 12.5, color: C.accent5, paraSpaceAfter: 3 });
  s.addNotes("Security is part of the product flow, not a paragraph in a prompt. T0 provides information, T1 advises, T2 creates draft orders and T3 executes only after a human confirmation token. The token is bound to the exact order summary, expires and can be used once. Suitability, cash, limits, profile expiry and cooling-off checks run on the server before execution. A kill switch caps sessions at advice. Personal identifiers are masked before any model call. Our deterministic red-team suite stopped all 57 attack cases and still handled all eight benign controls. The tests do not replace formal security review or regulatory approval.");
}

// ------------------------------------------------------------------ 9 results
pres.addSection({ title: "Results and fit" });
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Results and fit" });
  s.addText("Measured, not claimed", { placeholder: "title" });
  const stats = [
    [NUMBERS.journeys, "client journeys completed end to end on a live model: 30 scripted clients across C1 to C5, one in five in Chinese"],
    [NUMBERS.redteam, "red-team attacks stopped across 12 categories, with no harmless request refused"],
    [NUMBERS.tests, "automated tests, run offline in CI; a FISCO BCOS round trip runs when the chain is up"],
    [NUMBERS.backtest, "risk classes stayed inside their volatility band from 2008 to 2026"],
  ];
  const tw = (W - 2 * M) / 4;
  rule(s, M, 1.55, W - 2 * M, RULE_STRONG, "stats-top");
  stats.forEach(([n, label], i) => {
    const x = M + i * tw;
    if (i) vrule(s, x, 1.55, 2.55, RULE, `stat-divider-${i}`);
    const px = x + (i ? 0.3 : 0);
    text(s, n, { x: px, y: 1.75, w: tw - 0.5, h: 0.9, fontSize: 40, bold: true, color: C.accent1 });
    text(s, label, { x: px, y: 2.7, w: tw - 0.55, h: 1.3, fontSize: 12.5, color: C.accent5 });
  });
  rule(s, M, 4.1, W - 2 * M, RULE, "stats-bottom");
  text(s, "What the backtest taught us", { x: M, y: 4.45, w: 6, h: 0.4, fontSize: 15, bold: true, color: C.accent2 });
  text(s, "Every class kept its volatility target for 18 years, yet every class fell further than that number suggests: C5 lost 34% in 2008. A volatility figure does not tell a client what 2008 feels like. That is why Keel enforces the client's own loss limit and has them rehearse the crash.", { x: M, y: 4.9, w: W - 2 * M - 1, h: 1.3, fontSize: 17, color: C.text1 });
  s.addNotes("Here is the measured result. All 30 scripted client journeys completed on the live model, balanced across C1 to C5, with six in Chinese. The red-team suite stopped 57 attacks, and eight benign requests still worked. The offline suite passed 156 tests, including a local FISCO BCOS round trip and tamper check. In a backtest from 2008 to 2026, all five classes stayed inside their volatility targets, but losses still exceeded what the volatility number alone might lead a client to expect; C5 lost 34 percent in 2008. One practical limit is speed: a live journey took a median of about 129 seconds. Groq quota or network availability can affect a live demo, so the deterministic replay path remains our backup.");
}

// ------------------------------------------------------------------ 10 architecture
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Results and fit" });
  s.addText("Architecture", { placeholder: "title" });
  const iw = 7.4, ih = iw * 0.7;
  s.addImage({ path: ASSET("architecture.png"), x: M, y: 1.45, w: iw, h: ih, altText: "Architecture: web UI and FastAPI server; advisory core with input guard, agent loop, output guard and tool dispatcher; untrusted language model; deterministic engine; client-only actions; audit log anchored on FISCO BCOS", objectName: "architecture" });
  const rx = M + iw + 0.5, rw = W - M - rx;
  vrule(s, rx - 0.25, 1.55, 5.0, RULE, "arch-divider");
  const notes = [
    ["The model is untrusted", "It can only talk and request tools. It never sees personal data and cannot reach the account."],
    ["Versioned advice", "Advice binds the profile, goal, catalog and calculation versions. Material changes make old advice stale."],
    ["Stage-aware tools", "Each stage exposes only valid tools, with at most eight model steps per turn. Offline tests need no API key."],
  ];
  notes.forEach(([h2, body], i) => {
    const y = 1.55 + i * 1.65;
    if (i) rule(s, rx, y - 0.15, rw, RULE, `arch-rule-${i}`);
    text(s, h2, { x: rx, y, w: rw, h: 0.35, fontSize: 15, bold: true, color: C.text1 });
    text(s, body, { x: rx, y: y + 0.4, w: rw, h: 1.1, fontSize: 13, color: C.accent5 });
  });
  s.addNotes("The architecture makes those boundaries explicit. The UI talks to a FastAPI server; a bounded agent loop sees only tools valid for the current stage. Input checks mask identifiers and catch known injection patterns, and output checks ground numbers. Each recommendation is a versioned record that binds the investor profile, goal, catalog snapshot and calculation version. A material change makes that recommendation stale. Consent and any order proposal refer to the same fingerprint, so approval cannot silently carry over to changed advice. Deterministic Python computes the financial results; a separate permission layer controls simulated account actions. Finally, the audit chain records the decisions and anchors its head on FISCO BCOS.");
}

// ------------------------------------------------------------------ 11 WeBank fit
{
  const s = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Results and fit" });
  s.addText("Built for a bank like WeBank", { placeholder: "title" });
  const items = [
    ["FISCO BCOS", "Built", "Advisory records anchored on WeBank's consortium chain. In production the nodes would be run by the bank, an auditor and the regulator."],
    ["FATE federated learning", "Next", "Crash Rehearsal creates a new signal, revealed risk tolerance. Banks could learn to predict it from questionnaires with FATE without pooling client data."],
    ["Fund distribution", "Built", "Real public funds with distributor risk levels: the products a digital bank already sells."],
    ["Bilingual by design", "Built", "English and 简体中文 throughout, for Shenzhen and clients across the region."],
  ];
  const cw = (W - 2 * M) / 2;
  rule(s, M, 1.55, W - 2 * M, RULE_STRONG, "fit-top");
  rule(s, M, 4.0, W - 2 * M, RULE, "fit-middle");
  vrule(s, M + cw, 1.55, 4.9, RULE, "fit-divider");
  items.forEach(([head, status, body], i) => {
    const x = M + (i % 2) * cw + (i % 2 ? 0.4 : 0), y = 1.8 + Math.floor(i / 2) * 2.45;
    const w = cw - 0.6;
    text(s, head, { x, y, w: w - 1.2, h: 0.4, fontSize: 18, bold: true, color: C.text1 });
    text(s, status, { x: x + w - 1.0, y, w: 1.0, h: 0.4, fontSize: 13, bold: true, color: status === "Built" ? C.accent1 : C.accent2, align: "right" });
    text(s, body, { x, y: y + 0.55, w, h: 1.4, fontSize: 14, color: C.accent5 });
  });
  s.addNotes("Why does this fit WeBank? Keel already anchors records on FISCO BCOS, the consortium chain associated with WeBank, and uses real Chinese public funds with distributor risk levels. The prototype runs a local four-node chain; a bank would use its approved production infrastructure and controls. The interface supports English and Simplified Chinese. FATE federated learning is a possible next research step: banks could study whether questionnaire answers predict revealed tolerance while keeping raw rehearsal data local. We have not implemented FATE in this prototype, so it remains a proposal rather than a claimed capability.");
}

// ------------------------------------------------------------------ 12 close
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Results and fit" });
  s.addImage({ path: ASSET("mark_light.png"), x: M, y: 0.7, w: 0.5, h: 0.5, altText: "Keel logo", objectName: "logo-close" });
  text(s, "Advice you can check.", { x: M, y: 1.9, w: 11, h: 1.4, fontSize: 60, bold: true, color: C.background1, valign: "bottom" });
  text(s, "Rehearse the crash before investing. Ground every number in code. Let only the client move money. Anchor the record on chain.", { x: M, y: 3.6, w: 10.8, h: 1.1, fontSize: 21, color: SEA_DIM });
  rule(s, M, 5.75, W - 2 * M, SEA_RULE, "close-rule");
  text(s, "Code and documentation: github.com/erkinovvv/keel\nTeam Keel   Westminster International University in Tashkent", { x: M, y: 5.95, w: 11.5, h: 0.75, fontSize: 14, color: SEA_DIM, lineSpacingMultiple: 1.2 });
  s.addNotes("Keel gives a client a way to rehearse a hard decision before investing. It grounds every number in code, ties each consent to the exact advice version and leaves a record that can be checked afterwards. The simulated account makes the prototype’s safety boundary clear. Thank you. We would be glad to walk through the live product and answer questions about its data, controls or financial assumptions.");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
