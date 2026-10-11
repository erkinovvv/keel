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
  li.textContent = text;
  thread.append(li);
  thread.scrollTop = thread.scrollHeight;
}
function note(text, cls = "msg-note") {
  const li = document.createElement("li");
  li.className = cls;
  li.textContent = text;
  thread.append(li);
  thread.scrollTop = thread.scrollHeight;
}

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chatInput");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autosize(input);
  clientSays(text);
  const send = $(".send");
  send.disabled = true;
  const typing = document.createElement("li");
  typing.className = "msg-advisor";
  typing.innerHTML = `<span class="typing" aria-label="Advisor is typing"><i></i><i></i><i></i></span>`;
  thread.append(typing);
  thread.scrollTop = thread.scrollHeight;
  try {
    const { reply } = await api("/api/chat", { method: "POST", body: { message: text } });
    typing.remove();
    say(esc(reply).split(/\n{2,}/).map((p) => p.replace(/\n/g, "<br>")));
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
  ({ profile: renderProfile, portfolio: renderPortfolio, compare: renderCompare, stress: renderStress, execute: renderExecute })[step]();
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
  Object.assign(state, { allocation: data.allocation, allocationProv: data.provenance, allocationLevel: level });
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
    <div class="actions"><button class="btn" type="button" id="toStress">Stress-test this portfolio</button><button class="btn secondary" type="button" id="toCompare">Compare products</button></div>
    <div id="allocErr"></div>`;

  panel.querySelectorAll("[data-why]").forEach((b) => (b.onclick = () => {
    const row = $(`#why${b.dataset.why}`);
    row.hidden = !row.hidden;
    b.setAttribute("aria-expanded", String(!row.hidden));
  }));
  panel.querySelectorAll("[data-level]").forEach((b) => (b.onclick = () => rebuild(+$("#wiAmount").value, +b.dataset.level)));
  let t;
  $("#wiAmount").oninput = (e) => { clearTimeout(t); t = setTimeout(() => rebuild(+e.target.value, state.allocationLevel), 450); };
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

// ---------------------------------------------------------------- 3. compare

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

// ---------------------------------------------------------------- 4. stress

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

// ---------------------------------------------------------------- 5. execute

function renderExecute() {
  panel.innerHTML = `
    <h1>Place orders</h1>
    <p class="lede">Orders run on a simulated brokerage account, and only after you confirm the exact order yourself. The advisor can never confirm on your behalf.</p>
    <div class="sheet locked">
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
      <div>
        <strong>This session is set to advice only.</strong>
        <ul class="tiers">
          <li><b>Info</b>Education and product facts</li>
          <li class="current"><b>Advise</b>Profiling, portfolios, stress tests (current)</li>
          <li><b>Propose</b>Draft orders for your review</li>
          <li><b>Execute</b>Run drafts after your one-time confirmation</li>
        </ul>
      </div>
    </div>`;
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
  go("profile");
  refreshAudit();
})();
