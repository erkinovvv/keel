// Wealth Advisor web UI. Every number shown is computed on the server by deterministic code;
// the UI only formats it and shows where it came from (provenance popover).

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const money = (v) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
const CLASS_NAMES = { 1: "Conservative", 2: "Moderately conservative", 3: "Balanced", 4: "Growth", 5: "Aggressive" };
const ASSET_ORDER = ["cash", "bonds", "equity", "gold", "reits"];
const ASSET_NAMES = { cash: "Cash", bonds: "Bonds", equity: "Equity", gold: "Gold", reits: "Real estate" };

const state = {
  questionnaire: [],
  profile: null,
  client: null,
  allocation: null,
  allocationLevel: null,
  step: "profile",
  done: new Set(),
  prov: new Map(),
};

// ---------------------------------------------------------------- API

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

// ---------------------------------------------------------------- provenance

let provSeq = 0;
function num(text, prov, what) {
  const id = `p${++provSeq}`;
  state.prov.set(id, { ...prov, what });
  return `<button type="button" class="num" data-prov="${id}">${text}</button>`;
}

const popover = $("#popover");
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".num");
  if (!btn) { if (!e.target.closest("#popover")) popover.hidden = true; return; }
  const p = state.prov.get(btn.dataset.prov);
  if (!p) return;
  popover.innerHTML = `
    <div class="t">${esc(p.what)}</div>
    <dl>
      <dt>Computed by</dt><dd>${esc(p.source)}()</dd>
      <dt>Audit record</dt><dd>${esc(p.audit_hash.slice(0, 16))}…</dd>
      <dt>Recorded</dt><dd>${esc(new Date(p.timestamp).toLocaleTimeString())}</dd>
    </dl>`;
  popover.hidden = false;
  const r = btn.getBoundingClientRect();
  const left = Math.min(window.innerWidth - 316, Math.max(16, r.left));
  const top = r.bottom + 8 + 150 > window.innerHeight ? r.top - popover.offsetHeight - 8 : r.bottom + 8;
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { popover.hidden = true; closeDrawer(); } });

// ---------------------------------------------------------------- advisor thread

const thread = $("#thread");
function say(paragraphs) {
  const li = document.createElement("li");
  li.className = "msg-advisor";
  li.innerHTML = `<div class="sig">Advisor</div>${paragraphs.map((p) => `<p>${p}</p>`).join("")}`;
  thread.append(li);
  thread.scrollTop = thread.scrollHeight;
}
function clientSays(text) {
  const li = document.createElement("li");
  li.className = "msg-client";
  const body = document.createElement("span");
  body.textContent = text;
  li.append(body);
  thread.append(li);
  thread.scrollTop = thread.scrollHeight;
  return li;
}
function note(text, cls = "msg-note") {
  const li = document.createElement("li");
  li.className = cls;
  li.textContent = text;
  thread.append(li);
  thread.scrollTop = thread.scrollHeight;
}

// ---------------------------------------------------------------- chat ↔ client file sync

function applyServerState(s, { fromChat = false } = {}) {
  if (!s) return;
  const changes = [];
  if (s.profile && (!state.profile || state.profile.investor_class !== s.profile.investor_class || state.profile.expires_on !== s.profile.expires_on || JSON.stringify(state.answers) !== JSON.stringify(s.answers))) {
    Object.assign(state, { profile: s.profile, answers: s.answers, allocationLevel: s.profile.investor_class });
    state.profileProv = state.profileProv || { source: "profiling.profile_investor", audit_hash: "0".repeat(64), timestamp: new Date().toISOString() };
    state.done.add("profile");
    $("#reportLink").setAttribute("aria-disabled", "false");
    changes.push(`risk profile C${s.profile.investor_class}`);
  }
  if (s.client && JSON.stringify(s.client) !== JSON.stringify(state.client)) {
    if (state.client && fromChat) changes.push("your details");
    state.client = { amount: 100000, horizon_years: 10, max_loss: 0.2, age: 35, ...Object.fromEntries(Object.entries(s.client).filter(([, v]) => v !== null)) };
  }
  if (s.allocation_id && s.allocation_id !== state.allocationId) {
    Object.assign(state, { allocation: s.allocation, allocationId: s.allocation_id, allocationProv: s.allocation_provenance, allocationLevel: s.allocation.investor_class, drafts: null });
    state.done.add("portfolio");
    changes.push("portfolio");
  }
  if (s.tier) setTier(s.tier);
  if (fromChat && changes.length) {
    note(`Client file updated from the conversation: ${changes.join(", ")}.`, "msg-sync");
    for (const b of steps.querySelectorAll("button")) b.disabled = b.dataset.step !== "profile" && !state.profile;
    const affected = { profile: changes.some((c) => c.startsWith("risk")), portfolio: changes.includes("portfolio") };
    if (affected[state.step] || (state.step === "profile" && state.profile)) go(state.step);
  }
}

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chatInput");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autosize(input);
  const bubble = clientSays(text);
  const send = $(".send");
  send.disabled = true;
  try {
    const r = await api("/api/redact", { method: "POST", body: { message: text } });
    if (r.pii_types.length) {
      scramble(bubble.firstChild, r.redacted);
      const tag = document.createElement("small");
      tag.className = "pii-tag";
      tag.textContent = `Masked before reaching the AI: ${r.pii_types.map((t) => t.toLowerCase().replace(/_/g, " ")).join(", ")}`;
      bubble.append(tag);
    }
  } catch { /* redaction display is best-effort; the server redacts regardless */ }
  const typing = document.createElement("li");
  typing.className = "msg-advisor";
  typing.innerHTML = `<span class="typing" aria-label="Advisor is typing"><i></i><i></i><i></i></span>`;
  thread.append(typing);
  thread.scrollTop = thread.scrollHeight;
  try {
    const res = await api("/api/chat", { method: "POST", body: { message: text } });
    typing.remove();
    say(esc(res.reply).split(/\n{2,}/).map((p) => p.replace(/\n/g, "<br>")));
    applyServerState(res.state, { fromChat: true });
  } catch (err) {
    typing.remove();
    note(err.message, "msg-error");
  } finally {
    send.disabled = false;
    refreshAudit();
  }
});
const autosize = (el) => { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 140)}px`; };
$("#chatInput").addEventListener("input", (e) => autosize(e.target));
$("#chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
});

// ---------------------------------------------------------------- steps

const panel = $("#panel");
const steps = $("#steps");
steps.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-step]");
  if (b && !b.disabled) go(b.dataset.step);
});
function go(step) {
  state.step = step;
  for (const b of steps.querySelectorAll("button")) {
    b.classList.toggle("active", b.dataset.step === step);
    b.classList.toggle("done", state.done.has(b.dataset.step) && b.dataset.step !== step);
    b.disabled = b.dataset.step !== "profile" && !state.profile;
  }
  popover.hidden = true;
  ({ profile: renderProfile, portfolio: renderPortfolio, goal: renderGoal, compare: renderCompare, stress: renderStress, execute: renderExecute })[step]();
  panel.scrollTop = 0;
}

// ---------------------------------------------------------------- 1. profile

function renderProfile() {
  const c = state.client || { amount: 100000, horizon_years: 10, max_loss: 0.2, age: 35 };
  const prev = state.answers || {};
  panel.innerHTML = `
    <h1>Let's understand your situation</h1>
    <p class="lede">Your risk class is the lower of two things: how much loss you can <em>afford</em> (capacity) and how much you are <em>comfortable</em> with (tolerance). Nothing here is shared outside this session.</p>
    <form id="kyc">
      <div class="sheet">
        <div class="facts">
          <div class="field"><label for="age">Age</label><input id="age" type="number" min="18" max="100" value="${c.age}" required></div>
          <div class="field"><label for="amount">Amount to invest</label><input id="amount" type="number" min="1000" step="1000" value="${c.amount}" required></div>
          <div class="field"><label for="horizon">Horizon <span class="range-value" id="horizonV">${c.horizon_years} yrs</span></label><input id="horizon" type="range" min="1" max="30" value="${c.horizon_years}"></div>
          <div class="field"><label for="maxloss">Loss you could accept in a bad year <span class="range-value" id="maxlossV">${Math.round(c.max_loss * 100)}%</span></label><input id="maxloss" type="range" min="5" max="50" value="${Math.round(c.max_loss * 100)}"></div>
          <label class="check"><input id="borrowed" type="checkbox"> Part of this money is borrowed</label>
        </div>
      </div>
      <div class="sheet">
        <div class="questions">
          ${state.questionnaire.map((q) => `
            <fieldset class="q">
              <legend>${esc(q.question)}<span class="domain">${q.domain === "capacity" ? "capacity" : "tolerance"}</span></legend>
              <div class="chips">
                ${q.options.map((o, i) => `
                  <label class="chip"><input type="radio" name="${q.key}" value="${o.key}" ${(prev[q.key] ? prev[q.key] === o.key : i === Math.floor(q.options.length / 2)) ? "checked" : ""}><span>${esc(o.label)}</span></label>`).join("")}
              </div>
            </fieldset>`).join("")}
        </div>
      </div>
      <div class="actions">
        <button class="btn" type="submit" id="assess">Assess my risk profile</button>
        <span class="hint">Scored by fixed rules, not by AI.</span>
      </div>
      <div id="kycErr"></div>
    </form>
    <div id="profileResult"></div>`;
  $("#horizon").oninput = (e) => ($("#horizonV").textContent = `${e.target.value} yrs`);
  $("#maxloss").oninput = (e) => ($("#maxlossV").textContent = `${e.target.value}%`);
  $("#kyc").onsubmit = submitProfile;
  if (state.profile) showProfile(false);
}

async function submitProfile(e) {
  e.preventDefault();
  const answers = Object.fromEntries(state.questionnaire.map((q) => [q.key, $(`input[name="${q.key}"]:checked`).value]));
  const btn = $("#assess");
  btn.disabled = true;
  $("#kycErr").innerHTML = "";
  try {
    const data = await api("/api/profile", {
      method: "POST",
      body: {
        answers,
        age: +$("#age").value,
        amount: +$("#amount").value,
        horizon_years: +$("#horizon").value,
        max_loss: +$("#maxloss").value / 100,
        borrowed_money: $("#borrowed").checked,
      },
    });
    Object.assign(state, { answers, profile: data.profile, client: data.client, profileProv: data.provenance, allocationLevel: data.profile.investor_class, allocation: null });
    state.done.add("profile");
    $("#reportLink").setAttribute("aria-disabled", "false");
    showProfile(true);
    go("profile");
    $("#profileResult").scrollIntoView({ behavior: "smooth", block: "start" });
    refreshAudit();
  } catch (err) {
    $("#kycErr").innerHTML = `<p class="err">${esc(err.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
}

function showProfile(narrate) {
  const p = state.profile;
  const prov = state.profileProv;
  const at = (cls) => `${(cls - 0.5) * 20}%`;
  $("#profileResult").innerHTML = `
    <h3>Your result</h3>
    <div class="sheet">
      <div class="verdict">
        <div>
          <div class="class-code">Risk class ${num(`C${p.investor_class}`, prov, "Investor risk class")}</div>
          <div class="class-name">${esc(p.class_name)}</div>
          <p>You can be recommended products up to risk level <strong>R${p.investor_class}</strong>. Profile valid until ${new Date(p.expires_on).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}.</p>
        </div>
        <div class="scale" aria-label="Capacity C${p.capacity_class}, tolerance C${p.tolerance_class}, final class C${p.investor_class}">
          <div class="marker top" style="left:${at(p.capacity_class)}">Capacity C${p.capacity_class}</div>
          <div class="scale-track">${[1, 2, 3, 4, 5].map((i) => `<div class="${i <= p.investor_class ? "on" : ""}"></div>`).join("")}</div>
          <div class="scale-labels">${[1, 2, 3, 4, 5].map((i) => `<span>C${i}</span>`).join("")}</div>
          <div class="marker bottom" style="left:${at(p.tolerance_class)}">Tolerance C${p.tolerance_class}</div>
        </div>
      </div>
      ${p.flags.map((f) => `<div class="flag"><svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg>${esc(f.text)}</div>`).join("")}
    </div>
    <h3>Why this class</h3>
    <div class="sheet"><ul class="reasons">${p.reasons.map((r) => `<li>${esc(r.text)}</li>`).join("")}</ul></div>
    <div class="actions"><button class="btn" id="toPortfolio" type="button">See my recommended portfolio</button></div>`;
  $("#toPortfolio").onclick = () => go("portfolio");
  if (narrate) {
    const lower = p.capacity_class <= p.tolerance_class ? "capacity" : "tolerance";
    say([
      `Your risk class is <strong>C${p.investor_class}, ${esc(p.class_name.toLowerCase())}</strong>.`,
      p.capacity_class === p.tolerance_class
        ? `Your ability to absorb losses and your comfort with risk point to the same level, C${p.capacity_class}.`
        : `Your comfort with risk is C${p.tolerance_class}, but your ${lower === "capacity" ? "financial capacity to absorb losses" : "comfort with risk"} is C${Math.min(p.capacity_class, p.tolerance_class)}. Suitability rules require me to use the lower of the two.`,
      ...(p.flags.length ? [`I have also applied a protection cap: ${esc(p.flags.map((f) => f.text.split(" — ")[0].toLowerCase()).join("; "))}.`] : []),
      `From here on I will only consider products rated R${p.investor_class} or lower.`,
    ]);
  }
}

// ---------------------------------------------------------------- 2. portfolio

async function loadAllocation(amount, level, narrate) {
  const data = await api("/api/allocation", { method: "POST", body: { amount, investor_class: level } });
  Object.assign(state, { allocation: data.allocation, allocationId: data.allocation_id, allocationProv: data.provenance, allocationLevel: level, drafts: null });
  state.done.add("portfolio");
  refreshAudit();
  if (narrate) {
    const a = data.allocation;
    const mix = ASSET_ORDER.filter((k) => a.by_asset_class[k]).map((k) => `${pct(a.by_asset_class[k], 0)} ${ASSET_NAMES[k].toLowerCase()}`).join(", ");
    say([
      `For ${money(a.amount)} I suggest ${mix}.`,
      `After fees, that mix has an expected return of about <strong>${pct(a.expected_return)}</strong> a year, with typical yearly swings of ${pct(a.volatility)}. These are estimates, not promises.`,
      `Tap any underlined number to see exactly which calculation produced it.`,
    ]);
  }
}

async function renderPortfolio() {
  const p = state.profile;
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">Building your portfolio…</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, true); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  const a = state.allocation;
  const prov = state.allocationProv;
  const mix = ASSET_ORDER.filter((k) => a.by_asset_class[k]);
  panel.innerHTML = `
    <h1>Your recommended portfolio</h1>
    <p class="lede">Built from your risk class with fixed allocation rules and a 35% cap per product. Only products rated R${a.investor_class} or lower are eligible.</p>
    <div class="kpis">
      <div class="kpi"><div class="k">Expected return</div><span class="v">${num(pct(a.expected_return, 2), prov, "Expected annual return, net of fees")}</span><div class="h">per year, after fees</div></div>
      <div class="kpi"><div class="k">Volatility</div><span class="v">${num(pct(a.volatility, 2), prov, "Annual portfolio volatility")}</span><div class="h">typical yearly swing</div></div>
      <div class="kpi"><div class="k">Average fee</div><span class="v">${num(pct(a.fee, 2), prov, "Weighted annual product fee")}</span><div class="h">per year</div></div>
      <div class="kpi"><div class="k">Value at risk</div><span class="v">${num(money(a.var_95_1y), prov, "1-year 95% parametric value at risk")}</span><div class="h">1 year, 95% confidence</div></div>
    </div>

    <div class="whatif">
      <div class="field"><label for="wiAmount">What if I invest</label><input id="wiAmount" type="number" min="1000" step="1000" value="${a.amount}"></div>
      <div class="field">
        <span class="label">What if I take less risk</span>
        <div class="seg" role="group" aria-label="Risk level">
          ${[1, 2, 3, 4, 5].map((i) => `<button type="button" data-level="${i}" class="${i === a.investor_class ? "on" : ""}" ${i > p.investor_class ? `disabled title="Above your assessed class C${p.investor_class}"` : ""}>C${i}</button>`).join("")}
        </div>
        <div class="hint">Levels above C${p.investor_class} are locked by the suitability rule.</div>
      </div>
    </div>

    <div class="sheet">
      <div class="mixbar" role="img" aria-label="${mix.map((k) => `${ASSET_NAMES[k]} ${pct(a.by_asset_class[k], 0)}`).join(", ")}">
        ${mix.map((k) => `<div style="flex-grow:${a.by_asset_class[k]};background:var(--${k})" title="${ASSET_NAMES[k]} ${pct(a.by_asset_class[k])}"></div>`).join("")}
      </div>
      <div class="legend">${mix.map((k) => `<span><i style="background:var(--${k})"></i>${ASSET_NAMES[k]} <b>${pct(a.by_asset_class[k], 0)}</b></span>`).join("")}</div>
    </div>

    <h3>Holdings</h3>
    <div class="sheet">
      <table>
        <thead><tr><th>Product</th><th>Risk</th><th class="r">Weight</th><th class="r">Amount</th><th></th></tr></thead>
        <tbody>
          ${a.holdings.map((h, i) => `
            <tr>
              <td class="prod"><span class="swatch" style="background:var(--${h.asset_class})"></span>${esc(h.name)}<small>${ASSET_NAMES[h.asset_class]}</small></td>
              <td><span class="risk">R${h.risk_class}</span></td>
              <td class="r">${num(pct(h.weight, 1), prov, `Weight of ${h.name}`)}</td>
              <td class="r">${num(money(h.amount), prov, `Amount in ${h.name}`)}</td>
              <td class="r"><button class="why" type="button" data-why="${i}" aria-expanded="false">Why?</button></td>
            </tr>
            <tr class="why-row" id="why${i}" hidden><td colspan="5"><ul>${h.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></td></tr>`).join("")}
        </tbody>
      </table>
    </div>
    <div class="actions"><button class="btn" type="button" id="toGoal">Check my goal</button><button class="btn secondary" type="button" id="toStress">Stress-test this portfolio</button><button class="btn secondary" type="button" id="toCompare">Compare products</button></div>
    <div id="allocErr"></div>`;

  panel.querySelectorAll("[data-why]").forEach((b) => (b.onclick = () => {
    const row = $(`#why${b.dataset.why}`);
    row.hidden = !row.hidden;
    b.setAttribute("aria-expanded", String(!row.hidden));
  }));
  panel.querySelectorAll("[data-level]").forEach((b) => (b.onclick = () => rebuild(+$("#wiAmount").value, +b.dataset.level)));
  let t;
  $("#wiAmount").oninput = (e) => { clearTimeout(t); t = setTimeout(() => rebuild(+e.target.value, state.allocationLevel), 450); };
  $("#toGoal").onclick = () => go("goal");
  $("#toStress").onclick = () => go("stress");
  $("#toCompare").onclick = () => go("compare");
}

async function rebuild(amount, level) {
  if (!(amount >= 1000)) return;
  try {
    await loadAllocation(amount, level, false);
    const focused = document.activeElement?.id;
    renderPortfolio();
    if (focused === "wiAmount") { const el = $("#wiAmount"); el.focus(); el.setSelectionRange?.(el.value.length, el.value.length); }
  } catch (err) {
    $("#allocErr").innerHTML = `<p class="err">${esc(err.message)}</p>`;
  }
}

// ---------------------------------------------------------------- 3. goal

const short = (v) => (v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : `${Math.round(v)}`);
const GOAL_KINDS = ["Buy a home", "Children's education", "Retirement", "Something else"];

async function renderGoal() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">Building your portfolio…</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, false); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  const g = state.goalInput || {
    name: GOAL_KINDS[0],
    target: Math.round((state.allocation.amount * 2.5) / 10000) * 10000,
    years: state.client.horizon_years,
    monthly: 1000,
    inflation: 0.02,
  };
  state.goalInput = g;
  panel.innerHTML = `
    <h1>Will you reach your goal?</h1>
    <p class="lede">We simulate 5,000 possible futures for your portfolio of ${money(state.allocation.amount)} and count how many reach your target. Same inputs always give the same answer.</p>
    <div class="sheet">
      <div class="filters" role="radiogroup" aria-label="Goal">
        ${GOAL_KINDS.map((k) => `<label class="chip"><input type="radio" name="gk" value="${esc(k)}" ${k === g.name ? "checked" : ""}><span>${esc(k)}</span></label>`).join("")}
      </div>
      <div class="facts">
        <div class="field"><label for="gTarget">Target amount</label><input id="gTarget" type="number" min="1000" step="1000" value="${g.target}"></div>
        <div class="field"><label for="gYears">In <span class="range-value" id="gYearsV">${g.years} yrs</span></label><input id="gYears" type="range" min="1" max="40" value="${g.years}"></div>
        <div class="field"><label for="gMonthly">Monthly saving</label><input id="gMonthly" type="number" min="0" step="100" value="${g.monthly}"></div>
        <label class="check"><input id="gInfl" type="checkbox" ${g.inflation ? "checked" : ""}> Target in today's money (2% inflation)</label>
      </div>
    </div>
    <div id="goalOut"><p class="empty" style="margin-top:20px">Simulating…</p></div>`;
  const read = () => ({
    name: $('input[name="gk"]:checked').value,
    target: +$("#gTarget").value,
    years: +$("#gYears").value,
    monthly: +$("#gMonthly").value,
    inflation: $("#gInfl").checked ? 0.02 : 0,
  });
  let t;
  const update = () => { clearTimeout(t); t = setTimeout(() => runGoal(read()), 250); };
  panel.querySelectorAll('input[name="gk"]').forEach((i) => (i.onchange = update));
  $("#gYears").oninput = (e) => { $("#gYearsV").textContent = `${e.target.value} yrs`; update(); };
  ["gTarget", "gMonthly"].forEach((id) => ($(`#${id}`).oninput = update));
  $("#gInfl").onchange = update;
  runGoal(g);
}

async function runGoal(input) {
  if (!(input.target > 0) || input.monthly < 0) return;
  state.goalInput = input;
  let data;
  try { data = await api("/api/goal", { method: "POST", body: input }); }
  catch (err) { $("#goalOut").innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  refreshAudit();
  const r = data.result;
  const prov = data.provenance;
  const year = new Date().getFullYear() + input.years;
  const chance = Math.round(r.probability * 100);
  const tone = r.probability >= 0.8 ? "ok" : r.probability >= 0.5 ? "mid" : "low";
  $("#goalOut").innerHTML = `
    <div class="goal-head">
      <div class="goal-chance">${num(`${chance}%`, prov, "Share of simulated futures that reach the target")}</div>
      <div>
        <span class="tone ${tone}">${tone === "ok" ? "On track" : tone === "mid" ? "Possible" : "Unlikely"}</span>
        <div class="goal-line">chance of reaching <b>${money(r.target_nominal)}</b> by ${year}</div>
        <div class="hint">${input.inflation ? `${money(input.target)} in today's money, grown by 2% inflation a year.` : "Nominal target, no inflation adjustment."}</div>
      </div>
    </div>
    ${r.required_monthly === null ? "" : r.required_monthly <= input.monthly
      ? `<div class="verdict-bar ok"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg><div><strong>You are on track.</strong> Your saving already gives at least an 80% chance.</div></div>`
      : `<div class="verdict-bar nudge"><div>Save <strong>${num(money(r.required_monthly), prov, "Monthly saving needed for an 80% chance")}</strong> a month to reach an 80% chance.</div><button class="btn secondary" type="button" id="useMonthly">Use ${money(r.required_monthly)} a month</button></div>`}
    <div class="sheet" style="margin-top:16px">
      ${fanChart(r.fan, r.target_nominal)}
      <div class="legend fan-legend">
        <span><i class="band-outer"></i>8 in 10 futures</span>
        <span><i class="band-inner"></i>Half of futures</span>
        <span><i class="line-median"></i>Median</span>
        <span><i class="line-target"></i>Your target</span>
      </div>
    </div>
    <div class="kpis" style="margin-top:16px;grid-template-columns:repeat(3,1fr)">
      <div class="kpi"><div class="k">Bad case (1 in 10)</div><span class="v">${num(money(r.terminal_p10), prov, "10th percentile outcome")}</span></div>
      <div class="kpi"><div class="k">Median outcome</div><span class="v">${num(money(r.terminal_p50), prov, "Median outcome")}</span></div>
      <div class="kpi"><div class="k">Good case (1 in 10)</div><span class="v">${num(money(r.terminal_p90), prov, "90th percentile outcome")}</span></div>
    </div>
    <details class="assume"><summary>Assumptions</summary><ul>${r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>`;
  const use = $("#useMonthly");
  if (use) use.onclick = () => { $("#gMonthly").value = r.required_monthly; runGoal({ ...input, monthly: r.required_monthly }); };
  wireFan(r.fan, r.target_nominal);
  state.done.add("goal");
  if (!state.goalNarrated) {
    state.goalNarrated = true;
    say([
      `With ${money(input.monthly)} a month, about <strong>${chance} in 100</strong> simulated futures reach ${money(r.target_nominal)} by ${year}.`,
      r.required_monthly && r.required_monthly > input.monthly
        ? `Saving ${money(r.required_monthly)} a month would lift that to <strong>80 in 100</strong>. A longer horizon also helps. Taking more risk than your class allows is not an option I can offer.`
        : "That is a comfortable margin. Keep the plan under review once a year.",
    ]);
  }
}

function fanChart(fan, target) {
  const W = 720, H = 280, L = 52, R = 16, T = 16, B = 30;
  const maxY = Math.max(target, ...fan.map((f) => f.p90)) * 1.08;
  const n = fan.length - 1;
  const x = (i) => L + (i / n) * (W - L - R);
  const y = (v) => T + (1 - v / maxY) * (H - T - B);
  const area = (lo, hi) => `M${fan.map((f, i) => `${x(i)},${y(f[hi])}`).join("L")}L${fan.map((f, i) => `${x(n - i)},${y(fan[n - i][lo])}`).join("L")}Z`;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((k) => k * maxY);
  const step = n > 20 ? 5 : n > 10 ? 2 : 1;
  return `
    <svg class="fan" id="fan" viewBox="0 0 ${W} ${H}" role="img" aria-label="Projected value over ${n} years: median ${money(fan[n].p50)}, target ${money(target)}">
      ${ticks.map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${short(v)}</text>`).join("")}
      ${fan.filter((_, i) => i % step === 0).map((f) => `<text class="axis" x="${x(f.year)}" y="${H - 8}" text-anchor="middle">${f.year === 0 ? "Now" : `${f.year}y`}</text>`).join("")}
      <path class="band-outer" d="${area("p10", "p90")}"/>
      <path class="band-inner" d="${area("p25", "p75")}"/>
      <path class="median" d="M${fan.map((f, i) => `${x(i)},${y(f.p50)}`).join("L")}"/>
      <line class="target" x1="${L}" x2="${W - R}" y1="${y(target)}" y2="${y(target)}"/>
      <text class="target-label" x="${L + 8}" y="${y(target) - 7}" text-anchor="start">Target ${short(target)}</text>
      <line class="cross" id="fanCross" y1="${T}" y2="${H - B}" visibility="hidden"/>
      <circle class="cross-dot" id="fanDot" r="5" visibility="hidden"/>
      <rect id="fanHit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>
    </svg>
    <div class="fan-tip" id="fanTip" hidden></div>`;
}

function wireFan(fan, target) {
  const svg = $("#fan");
  const hit = $("#fanHit");
  const tip = $("#fanTip");
  if (!svg) return;
  const W = 720, L = 52, R = 16, T = 16, B = 30, H = 280;
  const n = fan.length - 1;
  const maxY = Math.max(target, ...fan.map((f) => f.p90)) * 1.08;
  const show = (evt) => {
    const box = svg.getBoundingClientRect();
    const sx = ((evt.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(n, Math.round(((sx - L) / (W - L - R)) * n)));
    const f = fan[i];
    const px = L + (i / n) * (W - L - R);
    const py = T + (1 - f.p50 / maxY) * (H - T - B);
    $("#fanCross").setAttribute("x1", px); $("#fanCross").setAttribute("x2", px); $("#fanCross").setAttribute("visibility", "visible");
    $("#fanDot").setAttribute("cx", px); $("#fanDot").setAttribute("cy", py); $("#fanDot").setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${i === 0 ? "Today" : `Year ${i}`}</b><div>Median ${money(f.p50)}</div><div class="dim">8 in 10 between ${short(f.p10)} and ${short(f.p90)}</div>`;
    tip.hidden = false;
    const left = (px / W) * box.width;
    tip.style.left = `${Math.min(box.width - 190, Math.max(0, left + 12))}px`;
    tip.style.top = `${(py / H) * box.height - 20}px`;
  };
  const hide = () => { tip.hidden = true; $("#fanCross").setAttribute("visibility", "hidden"); $("#fanDot").setAttribute("visibility", "hidden"); };
  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerleave", hide);
}

// ---------------------------------------------------------------- 4. compare

async function renderCompare(asset = "") {
  panel.innerHTML = `<p class="empty">Comparing products…</p>`;
  let data;
  try { data = await api(`/api/compare${asset ? `?asset_class=${asset}` : ""}`); }
  catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  state.done.add("compare");
  refreshAudit();
  const prov = data.provenance;
  const c = state.client;
  panel.innerHTML = `
    <h1>Compare products</h1>
    <p class="lede">Every product you are eligible for, ranked by return per unit of risk after fees. Fee cost shows what fees would take from ${money(c.amount)} over ${c.horizon_years} years.</p>
    <div class="filters">
      ${["", ...ASSET_ORDER].map((k) => `<label class="chip"><input type="radio" name="af" value="${k}" ${k === asset ? "checked" : ""}><span>${k ? ASSET_NAMES[k] : "All"}</span></label>`).join("")}
    </div>
    <div class="sheet">
      ${data.rows.length ? `
      <table>
        <thead><tr><th>Product</th><th>Risk</th><th class="r">Return after fees</th><th class="r">Volatility</th><th class="r">Fee</th><th class="r">Fee cost</th><th class="r">Access</th></tr></thead>
        <tbody>
          ${data.rows.map((r) => `
            <tr>
              <td class="prod"><span class="swatch" style="background:var(--${r.asset_class})"></span>${esc(r.name)}<small>${ASSET_NAMES[r.asset_class]}</small></td>
              <td><span class="risk">R${r.risk_class}</span></td>
              <td class="r">${num(pct(r.net_return, 2), prov, `Expected return after fees: ${r.name}`)}</td>
              <td class="r">${pct(r.volatility, 1)}</td>
              <td class="r">${pct(r.fee, 2)}</td>
              <td class="r">${num(money(r.fee_drag), prov, `Fee cost over ${c.horizon_years} years: ${r.name}`)}</td>
              <td class="r">${r.liquidity_days <= 3 ? `${r.liquidity_days} day${r.liquidity_days > 1 ? "s" : ""}` : `${Math.round(r.liquidity_days / 30)} months`}</td>
            </tr>`).join("")}
        </tbody>
      </table>` : `<p class="empty">No products in this group match your risk class.</p>`}
    </div>
    ${data.locked?.length ? `<p class="hidden-note">Not shown because you may need the money sooner than they allow withdrawals: ${data.locked.map((h) => esc(h.name)).join(", ")}.</p>` : ""}
    ${data.hidden.length ? `<p class="hidden-note">Not shown because they exceed R${state.profile.investor_class}: ${data.hidden.map((h) => `${esc(h.name)} (R${h.risk_class})`).join(", ")}.</p>` : ""}`;
  panel.querySelectorAll('input[name="af"]').forEach((i) => (i.onchange = () => renderCompare(i.value)));
}

// ---------------------------------------------------------------- 5. stress

async function renderStress() {
  if (!state.allocation) { await renderPortfolio(); }
  panel.innerHTML = `<p class="empty">Running scenarios…</p>`;
  let data;
  try { data = await api("/api/stress"); }
  catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  state.done.add("stress");
  refreshAudit();
  const prov = data.provenance;
  const max = Math.max(data.max_loss, ...data.scenarios.map((s) => s.loss)) * 1.3;
  const x = (v) => `${(v / max) * 100}%`;
  const breaches = data.scenarios.filter((s) => s.breach);
  panel.innerHTML = `
    <h1>How would this portfolio have fared?</h1>
    <p class="lede">We replay three historical shocks on your current portfolio of ${money(state.allocation.amount)} and compare the loss with the ${pct(data.max_loss, 0)} you said you could accept.</p>
    <div class="sheet" style="padding-top:40px">
      ${data.scenarios.map((s, i) => `
        <div class="stress-row">
          <div class="name">${esc(s.name[0].toUpperCase() + s.name.slice(1))}</div>
          <div class="stress-track">
            <div class="stress-bar ${s.breach ? "breach" : ""}" style="width:${x(s.loss)}"></div>
            <div class="stress-val" style="left:${x(s.loss)}">−${pct(s.loss)} <span style="font-weight:400;color:var(--ink-3)">(${num(money(s.loss_amount), prov, `Loss in ${s.name}`)})</span></div>
            <div class="limit" style="left:${x(data.max_loss)}"></div>
            ${i === 0 ? `<div class="limit-label" style="left:${x(data.max_loss)}">Your limit ${pct(data.max_loss, 0)}</div>` : ""}
          </div>
        </div>`).join("")}
      <div class="verdict-bar ${breaches.length ? "bad" : "ok"}">
        ${breaches.length
          ? `<svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg><div><strong>Exceeds your limit in ${breaches.length} of ${data.scenarios.length} scenarios.</strong> Consider a lower risk level on the Portfolio step.</div>`
          : `<svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg><div><strong>Within your limit in every scenario.</strong> The worst case is a ${pct(Math.max(...data.scenarios.map((s) => s.loss)))} fall.</div>`}
      </div>
    </div>
    <p class="hint">Shocks are applied per asset class from historical peak-to-trough moves. Real losses can be larger.</p>`;
  const worst = data.scenarios.reduce((a, b) => (b.loss > a.loss ? b : a));
  say([
    `In a repeat of the ${esc(worst.name)}, this portfolio would have fallen about <strong>${pct(worst.loss)}</strong>, or ${money(worst.loss_amount)}.`,
    breaches.length
      ? `That is more than the ${pct(data.max_loss, 0)} you told me you could accept, so I would not recommend proceeding at this risk level.`
      : `That stays within the ${pct(data.max_loss, 0)} you told me you could accept.`,
  ]);
}

// ---------------------------------------------------------------- 6. execute

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const shortDate = (iso) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

function setTier(t) {
  state.tier = t;
  const el = $(".tier");
  el.textContent = t.level >= 3 ? "Simulated trading on" : "Advice only";
  el.classList.toggle("live", t.level >= 3);
  el.title = t.level >= 3
    ? "You signed the risk disclosure. Orders still need your explicit hold-to-confirm."
    : "Permission tier: the advisor can explain and recommend, but cannot place orders.";
}

async function renderExecute() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">Building your portfolio…</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, false); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  let t;
  try { t = await api("/api/tier"); } catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  setTier(t);
  if (t.level < 3) renderDisclosure(t);
  else renderTicket();
}

function renderDisclosure(t) {
  const p = state.profile;
  panel.innerHTML = `
    <h1>Before you place orders</h1>
    <p class="lede">Orders run on a simulated brokerage account. Read the risks below and sign to switch this session from advice only to simulated trading. You will still confirm every order yourself.</p>
    <div class="sheet disclosure">
      <h3 style="margin-top:0">Risk disclosure</h3>
      <ul class="reasons">
        <li>Investments can fall in value and you may get back less than you invest.</li>
        <li>Expected returns and stress tests are model estimates. Past performance does not predict future results.</li>
        <li>Your risk class is C${p.investor_class}. Products above R${p.investor_class} are blocked for you.</li>
        <li>Products rated R4 or higher have a cooling-off period before they can be bought.</li>
        <li>The AI advisor can never place or confirm an order on your behalf.</li>
      </ul>
      ${t.kill_switch ? `<div class="verdict-bar bad"><div><strong>Trading is switched off for all sessions right now.</strong> You can still use every advice step.</div></div>` : `
      <form id="consent" class="sign">
        <label class="check" style="padding-top:18px"><input type="checkbox" id="accept"> I have read and understood these risks</label>
        <div class="field sign-field">
          <label for="signName">Sign with your full name</label>
          <input id="signName" type="text" autocomplete="name" placeholder="Your full name" maxlength="80">
          <div class="signature" aria-hidden="true"><span id="sigInk"></span></div>
        </div>
        <div class="actions"><button class="btn" id="signBtn" type="submit" disabled>Sign and enable simulated trading</button></div>
        <div id="consentErr"></div>
      </form>`}
    </div>`;
  if (t.kill_switch) return;
  const name = $("#signName");
  const accept = $("#accept");
  const sync = () => {
    $("#sigInk").textContent = name.value;
    $("#signBtn").disabled = !(accept.checked && name.value.trim().length >= 2);
  };
  name.oninput = sync;
  accept.onchange = sync;
  $("#consent").onsubmit = async (e) => {
    e.preventDefault();
    $("#signBtn").disabled = true;
    const ink = $("#sigInk");
    ink.classList.remove("write");
    void ink.offsetWidth;
    ink.classList.add("write");
    try {
      const res = await api("/api/consent", { method: "POST", body: { full_name: name.value, accepted: accept.checked } });
      setTier(res);
      refreshAudit();
      await new Promise((r) => setTimeout(r, reduceMotion ? 0 : 1100));
      say(["Thank you. Simulated trading is now enabled for this session.", "I have prepared an order ticket from your portfolio. Nothing is placed until you hold the confirm button yourself."]);
      renderTicket();
    } catch (err) {
      $("#consentErr").innerHTML = `<p class="err">${esc(err.message)}</p>`;
      $("#signBtn").disabled = false;
    }
  };
}

async function renderTicket() {
  panel.innerHTML = `<p class="empty">Preparing your order ticket…</p>`;
  if (!state.drafts) {
    try { state.drafts = await api("/api/orders/draft", { method: "POST" }); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
    refreshAudit();
  }
  const d = state.drafts;
  const now = d.orders.filter((o) => !o.cooling_off);
  const later = d.orders.filter((o) => o.cooling_off);
  const total = now.reduce((s, o) => s + o.amount, 0);
  panel.innerHTML = `
    <h1>Review and confirm</h1>
    <p class="lede">These orders match your recommended portfolio exactly. Every line passed the suitability, liquidity and limit checks on the server.</p>
    <div class="exec">
      <div class="ticket">
        <div class="ticket-head">
          <div><div class="ticket-sub">Order ticket</div><div class="ticket-title">Buy ${d.orders.length} product${d.orders.length > 1 ? "s" : ""}</div></div>
          <div class="ticket-acct"><div class="ticket-sub">Simulated cash</div><b>${num(money(d.cash), d.provenance, "Simulated account cash")}</b></div>
        </div>
        <div class="perf" aria-hidden="true"></div>
        <ul class="ticket-lines">
          ${d.orders.map((o) => `
            <li class="${o.cooling_off ? "muted" : ""}">
              <span class="swatch" style="background:var(--${o.asset_class})"></span>
              <span class="tl-name">${esc(o.name)}<small>R${o.risk_class} · ${o.units.toFixed(2)} units at ${o.nav.toFixed(2)}${o.cooling_off ? ` · cooling-off until ${shortDate(o.cooling_off_until)}` : ""}</small></span>
              <span class="tl-amt">${money(o.amount)}</span>
            </li>`).join("")}
        </ul>
        <div class="perf" aria-hidden="true"></div>
        <ul class="checks">
          <li>Every product is rated R${d.investor_class} or lower</li>
          <li>Per-order and daily limits respected</li>
          <li>Risk profile valid until ${new Date(state.profile.expires_on).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</li>
        </ul>
        <div class="ticket-total"><span>${later.length ? "Placed now" : "Total"}</span><b>${money(total)}</b></div>
      </div>

      <div class="confirm-zone">
        ${now.length ? `
        <button class="hold" id="hold" type="button" aria-describedby="holdHint">
          <span class="hold-label">Hold to place ${now.length} order${now.length > 1 ? "s" : ""}</span>
          <span class="hold-fill" aria-hidden="true">Hold to place ${now.length} order${now.length > 1 ? "s" : ""}</span>
        </button>
        <p class="hint" id="holdHint">Press and hold for 1.5 seconds. You can undo for 5 seconds afterwards.</p>` : `<p class="empty">All orders are in their cooling-off period.</p>`}
        <div id="execErr"></div>
        <div class="printer" id="printer" hidden>
          <div class="slot" aria-hidden="true"></div>
          <div class="paper-wrap"><div class="paper" id="paper"></div></div>
        </div>
      </div>
    </div>`;
  if (now.length) wireHold($("#hold"), now);
}

function wireHold(btn, orders) {
  const DURATION = 1500;
  let start = 0, raf = 0, progress = 0, done = false;
  const set = (p) => { progress = p; btn.style.setProperty("--p", p.toFixed(3)); };
  const tick = (t) => {
    const p = Math.min(1, (t - start) / DURATION);
    set(p);
    if (p >= 1) { done = true; complete(); return; }
    raf = requestAnimationFrame(tick);
  };
  const press = (e) => {
    if (done || btn.disabled) return;
    if (e.type === "keydown") { if (e.repeat || (e.key !== " " && e.key !== "Enter")) return; e.preventDefault(); }
    btn.classList.add("pressing");
    start = performance.now() - progress * DURATION;
    raf = requestAnimationFrame(tick);
  };
  const release = () => {
    if (done) return;
    cancelAnimationFrame(raf);
    btn.classList.remove("pressing");
    const from = progress, t0 = performance.now();
    const back = (t) => { const p = Math.max(0, from - (t - t0) / 300); set(p); if (p > 0 && !btn.classList.contains("pressing")) requestAnimationFrame(back); };
    requestAnimationFrame(back);
  };
  btn.addEventListener("pointerdown", press);
  btn.addEventListener("keydown", press);
  ["pointerup", "pointerleave", "pointercancel", "keyup", "blur"].forEach((ev) => btn.addEventListener(ev, release));
  btn.addEventListener("click", (e) => e.preventDefault());

  async function complete() {
    btn.classList.remove("pressing");
    btn.classList.add("armed");
    let tokens;
    try {
      tokens = (await api("/api/orders/tokens", { method: "POST", body: { order_ids: orders.map((o) => o.order_id) } })).tokens;
    } catch (err) {
      $("#execErr").innerHTML = `<p class="err">${esc(err.message)}</p>`;
      reset();
      return;
    }
    let left = 5;
    const zone = btn.parentElement;
    const undo = document.createElement("div");
    undo.className = "undo";
    undo.innerHTML = `<span>Placing orders in <b id="undoN">${left}</b> s</span><button type="button" class="btn secondary" id="undoBtn">Undo</button>`;
    btn.hidden = true;
    $("#holdHint").hidden = true;
    zone.prepend(undo);
    $("#undoBtn").focus();
    const timer = setInterval(async () => {
      left -= 1;
      if (left > 0) { $("#undoN").textContent = left; return; }
      clearInterval(timer);
      undo.innerHTML = `<span>Placing orders…</span>`;
      try {
        const result = await api("/api/orders/confirm", { method: "POST", body: { tokens } });
        undo.remove();
        printReceipt(result);
        refreshAudit();
      } catch (err) {
        undo.remove();
        $("#execErr").innerHTML = `<p class="err">${esc(err.message)}</p>`;
      }
    }, 1000);
    $("#undoBtn").onclick = () => {
      clearInterval(timer);
      undo.remove();
      btn.hidden = false;
      $("#holdHint").hidden = false;
      reset();
      note("Orders cancelled before they were sent. Nothing was placed.");
      btn.focus();
    };
  }
  function reset() { done = false; btn.classList.remove("armed"); set(0); }
}

function barcode(hash) {
  let x = 0;
  const bars = [];
  for (const ch of hash.slice(0, 40)) {
    const v = parseInt(ch, 16);
    const w = 1 + (v % 3);
    bars.push(`<rect x="${x}" width="${w}" height="34"/>`);
    x += w + 1 + ((v >> 2) % 2);
  }
  return `<svg class="barcode" viewBox="0 0 ${x} 34" preserveAspectRatio="none" aria-hidden="true">${bars.join("")}</svg>`;
}

function printReceipt(r) {
  const printer = $("#printer");
  const paper = $("#paper");
  const ts = new Date(r.provenance.timestamp);
  const later = (state.drafts?.orders || []).filter((o) => o.cooling_off);
  const settle = r.executed[0]?.settles_on;
  const line = (l, rgt) => `<div class="rl"><span>${l}</span><span>${rgt}</span></div>`;
  paper.innerHTML = `
    <div class="rc-head">Wealth Advisor<br>Simulated brokerage account</div>
    <div class="rc-center">Trade confirmation</div>
    <div class="rc-center rc-dim">${ts.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })} ${ts.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</div>
    <div class="rc-rule"></div>
    ${r.executed.map((o) => `
      <div class="rc-item">
        ${line(`BUY ${esc(o.name)}`, "")}
        ${line(`&nbsp;&nbsp;R${o.risk_class} · ${o.units.toFixed(2)} u @ ${o.nav.toFixed(2)}`, money(o.amount))}
      </div>`).join("")}
    ${later.map((o) => `
      <div class="rc-item rc-dim">
        ${line(`HOLD ${esc(o.name)}`, "")}
        ${line(`&nbsp;&nbsp;cooling-off until ${shortDate(o.cooling_off_until)}`, money(o.amount))}
      </div>`).join("")}
    ${r.failed.map((f) => `<div class="rc-item rc-fail">${line(`NOT PLACED ${esc(f.order_id)}`, "")}<div>&nbsp;&nbsp;${esc(f.reason)}</div></div>`).join("")}
    <div class="rc-rule"></div>
    ${line("<b>Total executed</b>", `<b>${money(r.total)}</b>`)}
    ${line("Cash remaining", money(r.cash))}
    ${settle ? line("Settlement", `T+2 · ${shortDate(settle)}`) : ""}
    <div class="rc-rule"></div>
    <div class="rc-dim">Audit record</div>
    <div class="rc-hash">${r.provenance.audit_hash.match(/.{1,4}/g).slice(0, 8).join(" ")}</div>
    ${barcode(r.provenance.audit_hash)}
    <div class="stamp" aria-label="Suitability checked">
      <span>Suitability checked</span>
      <b>C${r.investor_class} · all ≤ R${r.investor_class}</b>
    </div>`;
  printer.hidden = false;
  printer.classList.remove("printing");
  void printer.offsetWidth;
  printer.classList.add("printing");
  setTimeout(() => printer.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" }), 200);
  state.drafts = null;
  state.done.add("execute");
  anchorOnReceipt(paper);
  say([
    r.executed.length
      ? `Done. ${r.executed.length} order${r.executed.length > 1 ? "s" : ""} for <strong>${money(r.total)}</strong> ${r.executed.length > 1 ? "were" : "was"} placed on your simulated account and will settle in two business days.`
      : "No orders were placed.",
    ...(later.length ? [`${later.length} higher-risk order${later.length > 1 ? "s are" : " is"} held for the cooling-off period, as the rules require.`] : []),
    "The confirmation carries the audit-record hash, so this trade can be verified later.",
  ]);
}

async function anchorOnReceipt(paper) {
  const slot = document.createElement("div");
  slot.className = "rc-chain";
  slot.innerHTML = `<div class="rc-rule"></div><div class="rc-dim">On-chain proof</div><div>Anchoring on Ethereum Sepolia…</div>`;
  paper.insertBefore(slot, paper.querySelector(".stamp"));
  try {
    const a = await api("/api/anchor", { method: "POST" });
    slot.lastElementChild.innerHTML = a.sent
      ? `Ethereum Sepolia · <a href="${esc(a.explorer_url)}" target="_blank" rel="noopener">${esc(a.tx_hash.slice(0, 10))}…${esc(a.tx_hash.slice(-6))}</a><br><span class="rc-dim">audit head after ${a.record_count} records</span>`
      : `<span class="rc-dim">Not anchored: ${esc(a.note)}</span>`;
    refreshAudit();
  } catch (err) {
    slot.lastElementChild.innerHTML = `<span class="rc-dim">Not anchored: ${esc(err.message)}</span>`;
  }
}

// ---------------------------------------------------------------- PII scramble (chat)

function scramble(el, target) {
  const from = el.textContent;
  if (reduceMotion || from === target) { el.textContent = target; return; }
  const glyphs = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%*";
  const len = Math.max(from.length, target.length);
  const frames = 26;
  let f = 0;
  const step = () => {
    f += 1;
    let out = "";
    for (let i = 0; i < len; i++) {
      const settle = (i / len) * frames * 0.7 + 6;
      const a = from[i] ?? "", b = target[i] ?? "";
      if (f >= settle) out += b;
      else if (a === b) out += a;
      else out += glyphs[(Math.random() * glyphs.length) | 0];
    }
    el.textContent = out;
    if (f < frames + 6) setTimeout(step, 28);
    else el.textContent = target;
  };
  step();
}

// ---------------------------------------------------------------- audit drawer

const drawer = $("#drawer");
const scrim = $("#scrim");
let lastFocus = null;
async function refreshAudit() {
  try {
    const a = await api("/api/audit");
    const pill = $("#auditPill");
    pill.classList.toggle("ok", a.valid);
    pill.classList.toggle("bad", !a.valid);
    $("#auditText").textContent = a.valid ? `Audit chain verified · ${a.total}` : "Audit chain broken";
    return a;
  } catch { return null; }
}
async function openDrawer() {
  lastFocus = document.activeElement;
  const a = await refreshAudit();
  if (!a) return;
  $("#drawerStatus").textContent = a.valid
    ? `${a.total} records. Each one includes the hash of the record before it, so editing any past entry breaks the chain.`
    : `Verification failed: ${a.reason}`;
  renderAnchors();
  $("#chain").innerHTML = a.records.map((r) => `
    <li>
      <div class="ev">${esc(r.event.replace(/_/g, " "))}</div>
      <div class="src">${esc(new Date(r.timestamp).toLocaleString())}${r.source ? ` · ${esc(r.source)}` : ""}</div>
      <div class="h">${esc(r.hash.slice(0, 20))}… ← ${esc((r.prev_hash || "genesis").slice(0, 12))}</div>
    </li>`).join("");
  drawer.hidden = false;
  scrim.hidden = false;
  $("#drawerClose").focus();
}
async function renderAnchors() {
  const box = $("#anchors");
  let list = [];
  try { list = await api("/api/anchors"); } catch { /* drawer still works without anchors */ }
  const sent = list.filter((x) => x.sent);
  box.innerHTML = `
    <div class="anchor-head">
      <div><b>Blockchain anchors</b><div class="hint">${sent.length ? `${sent.length} on Ethereum Sepolia` : "Write the current chain head to a public blockchain."}</div></div>
      <button class="btn secondary" type="button" id="anchorNow">Anchor now</button>
    </div>
    ${sent.slice().reverse().map((x) => `
      <div class="anchor-row">
        <a href="${esc(x.explorer_url)}" target="_blank" rel="noopener">${esc(x.tx_hash.slice(0, 12))}…</a>
        <span class="rc-dim">${x.record_count} records</span>
        <button class="why" type="button" data-verify="${esc(x.tx_hash)}">Verify</button>
        <span class="verify-out"></span>
      </div>`).join("")}
    ${list.length && !sent.length ? `<p class="hint">Last attempt: ${esc(list[list.length - 1].note)}</p>` : ""}`;
  $("#anchorNow").onclick = async (e) => {
    e.target.disabled = true;
    try { await api("/api/anchor", { method: "POST" }); } catch (err) { note(err.message, "msg-error"); }
    await openDrawer();
  };
  box.querySelectorAll("[data-verify]").forEach((b) => (b.onclick = async () => {
    const out = b.nextElementSibling;
    out.textContent = "Checking…";
    try {
      const v = await api(`/api/anchor/verify?tx=${b.dataset.verify}`);
      out.textContent = v.matches ? `✓ matches the log at record ${v.record_count}, block ${v.block}` : `✗ does not match (${v.chain_reason})`;
      out.className = `verify-out ${v.matches ? "ok" : "bad"}`;
    } catch (err) { out.textContent = err.message; }
  }));
}

function closeDrawer() {
  if (drawer.hidden) return;
  drawer.hidden = true;
  scrim.hidden = true;
  lastFocus?.focus();
}
$("#auditPill").onclick = openDrawer;
$("#drawerClose").onclick = closeDrawer;
scrim.onclick = closeDrawer;

// ---------------------------------------------------------------- boot

(async function boot() {
  say([
    "Hello. I'm your digital wealth advisor.",
    "Before I recommend anything, I need to understand how much risk you can afford and how much you are comfortable with. The short questionnaire on the right takes about two minutes.",
    "You can also ask me anything here at any time.",
  ]);
  try {
    state.questionnaire = await api("/api/questionnaire");
  } catch (err) {
    panel.innerHTML = `<p class="err">Could not load the questionnaire: ${esc(err.message)}</p>`;
    return;
  }
  try {
    const restored = await api("/api/state");
    applyServerState(restored);
    if (restored.profile) note("Welcome back. Your client file from this session is restored.");
  } catch { /* a fresh session simply starts at step 1 */ }
  go(state.profile ? (state.allocation ? "portfolio" : "profile") : "profile");
  refreshAudit();
})();
