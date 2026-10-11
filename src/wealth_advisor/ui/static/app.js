// Wealth Advisor web UI. Every number shown is computed on the server by deterministic code;
// the UI only formats it and shows where it came from (provenance popover).

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const longDate = (iso) => new Date(iso).toLocaleDateString(LOCALE, { day: "numeric", month: "short", year: "numeric" });
const money = (v) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
const ASSET_ORDER = ["cash", "bonds", "equity", "gold", "reits"];
const ASSET_NAMES = ASSET_NAMES_I18N[LANG];

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
      <dt>${t("Computed by")}</dt><dd>${esc(p.source)}()</dd>
      <dt>${t("Audit record")}</dt><dd>${esc(p.audit_hash.slice(0, 16))}…</dd>
      <dt>${t("Recorded")}</dt><dd>${esc(new Date(p.timestamp).toLocaleTimeString(LOCALE))}</dd>
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
  li.innerHTML = `<div class="sig">${t("Advisor")}</div>${paragraphs.map((p) => `<p>${p}</p>`).join("")}`;
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
    changes.push(t("risk profile C{n}", { n: s.profile.investor_class }));
  }
  if (s.client && JSON.stringify(s.client) !== JSON.stringify(state.client)) {
    if (state.client && fromChat) changes.push(t("your details"));
    state.client = { amount: 100000, horizon_years: 10, max_loss: 0.2, age: 35, ...Object.fromEntries(Object.entries(s.client).filter(([, v]) => v !== null)) };
  }
  if (s.allocation_id && s.allocation_id !== state.allocationId) {
    Object.assign(state, { allocation: s.allocation, allocationId: s.allocation_id, allocationProv: s.allocation_provenance, allocationLevel: s.allocation.investor_class, drafts: null });
    state.done.add("portfolio");
    changes.push(t("portfolio"));
  }
  if (s.tier) setTier(s.tier);
  if (fromChat && changes.length) {
    note(t("Client file updated from the conversation: {changes}.", { changes: changes.join(LANG === "zh" ? "、" : ", ") }), "msg-sync");
    for (const b of steps.querySelectorAll("button")) b.disabled = b.dataset.step !== "profile" && !state.profile;
    const affected = { profile: Boolean(s.profile), portfolio: changes.includes(t("portfolio")) };
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
      tag.textContent = t("Masked before reaching the AI: {types}", { types: r.pii_types.map((x) => x.toLowerCase().replace(/_/g, " ")).join(", ") });
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
  ({ profile: renderProfile, portfolio: renderPortfolio, rehearse: renderRehearse, goal: renderGoal, compare: renderCompare, stress: renderStress, execute: renderExecute })[step]();
  panel.scrollTop = 0;
}

// ---------------------------------------------------------------- 1. profile

function renderProfile() {
  const c = state.client || { amount: 100000, horizon_years: 10, max_loss: 0.2, age: 35 };
  const prev = state.answers || {};
  panel.innerHTML = `
    <h1>${t("Let's understand your situation")}</h1>
    <p class="lede">${t("Your risk class is the lower of two things: how much loss you can <em>afford</em> (capacity) and how much you are <em>comfortable</em> with (tolerance). Nothing here is shared outside this session.")}</p>
    <form id="kyc">
      <div class="sheet">
        <div class="facts">
          <div class="field"><label for="age">${t("Age")}</label><input id="age" type="number" min="18" max="100" value="${c.age}" required></div>
          <div class="field"><label for="amount">${t("Amount to invest")}</label><input id="amount" type="number" min="1000" step="1000" value="${c.amount}" required></div>
          <div class="field"><label for="horizon">${t("Horizon")} <span class="range-value" id="horizonV">${t("{n} yrs", { n: c.horizon_years })}</span></label><input id="horizon" type="range" min="1" max="30" value="${c.horizon_years}"></div>
          <div class="field"><label for="maxloss">${t("Loss you could accept in a bad year")} <span class="range-value" id="maxlossV">${Math.round(c.max_loss * 100)}%</span></label><input id="maxloss" type="range" min="5" max="50" value="${Math.round(c.max_loss * 100)}"></div>
          <label class="check"><input id="borrowed" type="checkbox"> ${t("Part of this money is borrowed")}</label>
        </div>
      </div>
      <div class="sheet">
        <div class="questions">
          ${state.questionnaire.map((q) => `
            <fieldset class="q">
              <legend>${esc(q.question)}<span class="domain">${t(q.domain === "capacity" ? "capacity" : "tolerance")}</span></legend>
              <div class="chips">
                ${q.options.map((o, i) => `
                  <label class="chip"><input type="radio" name="${q.key}" value="${o.key}" ${(prev[q.key] ? prev[q.key] === o.key : i === Math.floor(q.options.length / 2)) ? "checked" : ""}><span>${esc(o.label)}</span></label>`).join("")}
              </div>
            </fieldset>`).join("")}
        </div>
      </div>
      <div class="actions">
        <button class="btn" type="submit" id="assess">${t("Assess my risk profile")}</button>
        <span class="hint">${t("Scored by fixed rules, not by AI.")}</span>
      </div>
      <div id="kycErr"></div>
    </form>
    <div id="profileResult"></div>`;
  $("#horizon").oninput = (e) => ($("#horizonV").textContent = t("{n} yrs", { n: e.target.value }));
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
    <h3>${t("Your result")}</h3>
    <div class="sheet">
      <div class="verdict">
        <div>
          <div class="class-code">${t("Risk class")} ${num(`C${p.investor_class}`, prov, t("Investor risk class"))}</div>
          <div class="class-name">${esc(p.class_name)}</div>
          <p>${t("You can be recommended products up to risk level <strong>R{n}</strong>. Profile valid until {date}.", { n: p.investor_class, date: longDate(p.expires_on) })}</p>
        </div>
        <div class="scale" aria-label="Capacity C${p.capacity_class}, tolerance C${p.tolerance_class}, final class C${p.investor_class}">
          <div class="marker top" style="left:${at(p.capacity_class)}">${t("Capacity C{n}", { n: p.capacity_class })}</div>
          <div class="scale-track">${[1, 2, 3, 4, 5].map((i) => `<div class="${i <= p.investor_class ? "on" : ""}"></div>`).join("")}</div>
          <div class="scale-labels">${[1, 2, 3, 4, 5].map((i) => `<span>C${i}</span>`).join("")}</div>
          <div class="marker bottom" style="left:${at(p.tolerance_class)}">${t("Tolerance C{n}", { n: p.tolerance_class })}</div>
        </div>
      </div>
      ${p.flags.map((f) => `<div class="flag"><svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg>${esc(f.text)}</div>`).join("")}
    </div>
    <h3>${t("Why this class")}</h3>
    <div class="sheet"><ul class="reasons">${p.reasons.map((r) => `<li>${esc(r.text)}</li>`).join("")}</ul></div>
    <div class="actions"><button class="btn" id="toPortfolio" type="button">${t("See my recommended portfolio")}</button></div>`;
  $("#toPortfolio").onclick = () => go("portfolio");
  if (narrate) {
    const vars = { c: p.capacity_class, t: p.tolerance_class };
    say([
      t("Your risk class is <strong>C{n}, {name}</strong>.", { n: p.investor_class, name: esc(LANG === "zh" ? p.class_name : p.class_name.toLowerCase()) }),
      p.capacity_class === p.tolerance_class
        ? t("Your ability to absorb losses and your comfort with risk point to the same level, C{n}.", { n: p.capacity_class })
        : p.capacity_class < p.tolerance_class
          ? t("Your comfort with risk is C{t}, but your financial capacity to absorb losses is C{c}. Suitability rules require me to use the lower of the two.", vars)
          : t("Your financial capacity to absorb losses is C{c}, but your comfort with risk is C{t}. Suitability rules require me to use the lower of the two.", vars),
      ...(p.flags.length ? [t("I have also applied a protection cap: {flags}.", { flags: esc(p.flags.map((f) => f.text.split(/ — |：/)[0].toLowerCase()).join("; ")) })] : []),
      t("From here on I will only consider products rated R{n} or lower.", { n: p.investor_class }),
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
    const mix = ASSET_ORDER.filter((k) => a.by_asset_class[k]).map((k) => LANG === "zh" ? `${ASSET_NAMES[k]}${pct(a.by_asset_class[k], 0)}` : `${pct(a.by_asset_class[k], 0)} ${ASSET_NAMES[k].toLowerCase()}`).join(LANG === "zh" ? "、" : ", ");
    say([
      t("For {amount} I suggest {mix}.", { amount: money(a.amount), mix }),
      t("After fees, that mix has an expected return of about <strong>{ret}</strong> a year, with typical yearly swings of {vol}. These are estimates, not promises.", { ret: pct(a.expected_return), vol: pct(a.volatility) }),
      t("Tap any underlined number to see exactly which calculation produced it."),
      t("Before any money moves, I'd like you to live through 2008 with this exact portfolio. It takes 90 seconds and tells us both more than the questionnaire did. Open <strong>Rehearse</strong> when you're ready."),
    ]);
  }
}

function dataNote() {
  const c = state.catalog;
  if (!c?.real) return "";
  return `<p class="data-note"><span class="dot-live"></span>${t("{n} real Chinese public funds · public data as of {date} · amounts in {cur}", { n: c.count, date: longDate(c.as_of), cur: c.currency })}</p>`;
}

function staleBanner() {
  const a = state.allocation, p = state.profile;
  if (!a || !p || a.investor_class <= p.investor_class) return "";
  return `<div class="verdict-bar bad stale"><svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg><div><strong>${t("This portfolio was built for C{a}, but your risk class is now C{p}.", { a: a.investor_class, p: p.investor_class })}</strong> ${t("Rebuild it before placing any orders.")}</div><button class="btn" type="button" data-rebuild>${t("Rebuild at C{n}", { n: p.investor_class })}</button></div>`;
}

function wireStale() {
  panel.querySelectorAll("[data-rebuild]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    await loadAllocation(state.allocation.amount, state.profile.investor_class, true);
    go("portfolio");
  }));
}

async function renderPortfolio() {
  const p = state.profile;
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">${t("Building your portfolio…")}</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, true); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  const a = state.allocation;
  const prov = state.allocationProv;
  const mix = ASSET_ORDER.filter((k) => a.by_asset_class[k]);
  panel.innerHTML = `
    <h1>${t("Your recommended portfolio")}</h1>
    <p class="lede">${t("Built from your risk class with fixed allocation rules and a 35% cap per product. Only products rated R{n} or lower are eligible.", { n: a.investor_class })}</p>
    ${dataNote()}
    ${staleBanner()}
    <div class="kpis">
      <div class="kpi"><div class="k">${t("Expected return")}</div><span class="v">${num(pct(a.expected_return, 2), prov, t("Expected annual return, net of fees"))}</span><div class="h">${t("per year, after fees")}</div></div>
      <div class="kpi"><div class="k">${t("Volatility")}</div><span class="v">${num(pct(a.volatility, 2), prov, t("Annual portfolio volatility"))}</span><div class="h">${t("typical yearly swing")}</div></div>
      <div class="kpi"><div class="k">${t("Average fee")}</div><span class="v">${num(pct(a.fee, 2), prov, t("Weighted annual product fee"))}</span><div class="h">${t("per year")}</div></div>
      <div class="kpi"><div class="k">${t("Value at risk")}</div><span class="v">${num(money(a.var_95_1y), prov, t("1-year 95% parametric value at risk"))}</span><div class="h">${t("1 year, 95% confidence")}</div></div>
    </div>

    <div class="whatif">
      <div class="field"><label for="wiAmount">${t("What if I invest")}</label><input id="wiAmount" type="number" min="1000" step="1000" value="${a.amount}"></div>
      <div class="field">
        <span class="label">${t("What if I take less risk")}</span>
        <div class="seg" role="group" aria-label="${t("Risk level")}">
          ${[1, 2, 3, 4, 5].map((i) => `<button type="button" data-level="${i}" class="${i === a.investor_class ? "on" : ""}" ${i > p.investor_class ? `disabled title="${t("Above your assessed class C{n}", { n: p.investor_class })}"` : ""}>C${i}</button>`).join("")}
        </div>
        <div class="hint">${t("Levels above C{n} are locked by the suitability rule.", { n: p.investor_class })}</div>
      </div>
    </div>

    <div class="sheet">
      <div class="mixbar" role="img" aria-label="${mix.map((k) => `${ASSET_NAMES[k]} ${pct(a.by_asset_class[k], 0)}`).join(", ")}">
        ${mix.map((k) => `<div style="flex-grow:${a.by_asset_class[k]};background:var(--${k})" title="${ASSET_NAMES[k]} ${pct(a.by_asset_class[k])}"></div>`).join("")}
      </div>
      <div class="legend">${mix.map((k) => `<span><i style="background:var(--${k})"></i>${ASSET_NAMES[k]} <b>${pct(a.by_asset_class[k], 0)}</b></span>`).join("")}</div>
    </div>

    <h3>${t("Holdings")}</h3>
    <div class="sheet">
      <table>
        <thead><tr><th>${t("Product")}</th><th>${t("Risk")}</th><th class="r">${t("Weight")}</th><th class="r">${t("Amount")}</th><th></th></tr></thead>
        <tbody>
          ${a.holdings.map((h, i) => `
            <tr>
              <td class="prod"><span class="swatch" style="background:var(--${h.asset_class})"></span>${esc(h.name)}<small>${ASSET_NAMES[h.asset_class]}</small></td>
              <td><span class="risk">R${h.risk_class}</span></td>
              <td class="r">${num(pct(h.weight, 1), prov, t("Weight of {name}", { name: h.name }))}</td>
              <td class="r">${num(money(h.amount), prov, t("Amount in {name}", { name: h.name }))}</td>
              <td class="r"><button class="why" type="button" data-why="${i}" aria-expanded="false">${t("Why?")}</button></td>
            </tr>
            <tr class="why-row" id="why${i}" hidden><td colspan="5"><ul>${h.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}${h.source ? `<li><a href="${esc(h.source)}" target="_blank" rel="noopener">${t("Fund page and documents")}</a></li>` : ""}</ul></td></tr>`).join("")}
        </tbody>
      </table>
    </div>
    <div class="actions"><button class="btn" type="button" id="toRehearse">${t("Live through 2008 with this portfolio")}</button><button class="btn secondary" type="button" id="toGoal">${t("Check my goal")}</button><button class="btn secondary" type="button" id="toStress">${t("Stress-test this portfolio")}</button><button class="btn secondary" type="button" id="toCompare">${t("Compare products")}</button></div>
    <div id="allocErr"></div>`;

  panel.querySelectorAll("[data-why]").forEach((b) => (b.onclick = () => {
    const row = $(`#why${b.dataset.why}`);
    row.hidden = !row.hidden;
    b.setAttribute("aria-expanded", String(!row.hidden));
  }));
  panel.querySelectorAll("[data-level]").forEach((b) => (b.onclick = () => rebuild(+$("#wiAmount").value, +b.dataset.level)));
  let debounce;
  $("#wiAmount").oninput = (e) => { clearTimeout(debounce); debounce = setTimeout(() => rebuild(+e.target.value, state.allocationLevel), 450); };
  $("#toRehearse").onclick = () => go("rehearse");
  wireStale();
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

// ---------------------------------------------------------------- 3. crash rehearsal

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const monthName = (ym) => (LANG === "zh" ? `${ym.slice(0, 4)}年${+ym.slice(5)}月` : `${MONTHS[+ym.slice(5) - 1]} ${ym.slice(0, 4)}`);
const REACTION_TEXT = { sell_all: "sell everything", reduce: "sell some to limit losses", hold: "hold and wait", buy_more: "buy more at lower prices" };

async function renderRehearse() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">${t("Building your portfolio…")}</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, false); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  const last = state.rehearsal;
  const reaction = state.answers?.drawdown_reaction;
  panel.innerHTML = `
    <h1>${t("Before we invest, live through 2008")}</h1>
    <p class="lede">${t("Every robo-advisor stress-tests the portfolio. We stress-test the investor. You will replay October 2007 to March 2013 month by month, with real market returns, holding exactly the portfolio we just built for you. You can sell at any moment.")}</p>
    <div class="sheet rehearse-intro">
      <div class="ri-facts">
        <div><span>${t("Your portfolio")}</span><b>${money(state.allocation.amount)}</b></div>
        <div><span>${t("You told us that after a 20% fall you would")}</span><b>${esc(REACTION_TEXT[reaction] ? t(REACTION_TEXT[reaction]) : "—")}</b></div>
        <div><span>${t("The largest yearly loss you said you could accept")}</span><b>${state.client?.max_loss ? pct(state.client.max_loss, 0) : "—"}</b></div>
      </div>
      <p class="hint">${t("Takes about 90 seconds. What you do can only lower your risk class, never raise it. Data: Kenneth R. French Data Library, FRED, World Bank.")}</p>
      <div class="actions"><button class="btn" id="startRehearsal" type="button">${last ? t("Rehearse again") : t("Start the rehearsal")}</button></div>
    </div>
    <div id="rehearsalResult">${last ? resultCard(last) : ""}</div>`;
  $("#startRehearsal").onclick = startRehearsal;
  wireResult();
}

async function startRehearsal() {
  let data;
  try { data = await api("/api/rehearsal"); }
  catch (err) { note(err.message, "msg-error"); return; }
  refreshAudit();
  say([
    t("Let's live through it together. This is your portfolio, in real markets, starting October 2007."),
    t("If at any point you want out, press <strong>Sell everything</strong>. Doing nothing means you hold."),
  ]);
  const pts = data.points;
  const troughIndex = pts.reduce((best, p, i) => (p.drawdown > pts[best].drawdown ? i : best), 0);
  const stage = document.createElement("div");
  stage.className = "theater";
  stage.setAttribute("role", "dialog");
  stage.setAttribute("aria-label", t("Crash rehearsal"));
  stage.tabIndex = -1;
  const W = 1000, H = 300;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals) * 0.96, hi = Math.max(...vals) * 1.04;
  const X = (i) => (i / (pts.length - 1)) * W;
  const Y = (v) => H - ((v - lo) / (hi - lo)) * H;
  stage.innerHTML = `
    <div class="th-top">
      <div><div class="th-label">${t("Crash rehearsal · your portfolio")}</div><div class="th-month" id="thMonth">${monthName(pts[0].month)}</div></div>
      <button class="th-quit" id="thQuit" type="button">${t("Stop rehearsal")}</button>
    </div>
    <div class="th-value"><span id="thValue">${money(pts[0].value)}</span><span class="th-change" id="thChange">0.0%</span></div>
    <div class="th-dd" id="thDd">${t("From your peak: {dd}", { dd: "0.0%" })}</div>
    <svg class="th-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <line class="th-base" x1="0" x2="${W}" y1="${Y(data.amount)}" y2="${Y(data.amount)}"/>
      <path class="th-area" id="thArea" d=""/>
      <path class="th-line" id="thLine" d=""/>
      <circle class="th-dot" id="thDot" r="6" cx="0" cy="${Y(pts[0].value)}"/>
    </svg>
    <div class="th-news" aria-live="polite"><span class="th-news-tag">${t("News")}</span><span id="thNews">${t("Markets are calm. Stocks are near record highs.")}</span></div>
    <div class="th-actions">
      <button class="th-sell" id="thSell" type="button">${t("Sell everything")}</button>
      <button class="th-buy" id="thBuy" type="button">${t("Buy more")}</button>
      <span class="th-hint" id="thHint">${t("Doing nothing means you hold.")}</span>
    </div>`;
  document.body.append(stage);
  stage.focus();

  // ?demo plays the same months about three times faster, for recorded demos.
  const fast = new URLSearchParams(location.search).has("demo");
  const pace = { start: fast ? 600 : 1200, crash: fast ? 650 : 1500, recovery: fast ? 110 : 330 };
  let i = 0, done = false, boughtAt = null, timer = null;
  const tick = () => {
    if (done) return;
    i += 1;
    const p = pts[i];
    const line = pts.slice(0, i + 1).map((q, k) => `${k ? "L" : "M"}${X(k).toFixed(1)},${Y(q.value).toFixed(1)}`).join("");
    $("#thLine").setAttribute("d", line);
    $("#thArea").setAttribute("d", `${line}L${X(i).toFixed(1)},${H}L0,${H}Z`);
    $("#thDot").setAttribute("cx", X(i)); $("#thDot").setAttribute("cy", Y(p.value));
    const change = p.value / data.amount - 1;
    $("#thMonth").textContent = monthName(p.month);
    $("#thValue").textContent = money(p.value);
    $("#thChange").textContent = `${change >= 0 ? "+" : "−"}${pct(Math.abs(change))}`;
    $("#thDd").textContent = t("From your peak: {dd}", { dd: `−${pct(p.drawdown)}` });
    stage.classList.toggle("red", change < 0);
    stage.classList.toggle("deep", p.drawdown > 0.1);
    $("#thSell").classList.toggle("tempt", p.drawdown > 0.05 && i <= troughIndex + 2);
    if (p.headline) { const n = $("#thNews"); n.textContent = t(p.headline); n.classList.remove("flash"); void n.offsetWidth; n.classList.add("flash"); }
    if (i === troughIndex) $("#thHint").textContent = t("This is the moment most investors sell.");
    if (i === troughIndex + 3) $("#thHint").textContent = t("Doing nothing means you hold.");
    if (i >= pts.length - 1) return finish(boughtAt === null ? "hold" : "buy_more", boughtAt ?? i);
    timer = setTimeout(tick, i < troughIndex + 2 ? pace.crash : pace.recovery);
  };
  const finish = async (action, index) => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    stage.classList.add("ended");
    let res;
    try { res = await api("/api/rehearsal/decision", { method: "POST", body: { action, month_index: index } }); }
    catch (err) { stage.remove(); note(err.message, "msg-error"); return; }
    state.rehearsal = res.outcome;
    const lowered = res.outcome.new_class < res.outcome.previous_class;
    if (lowered) Object.assign(state, { profile: res.profile, allocationLevel: res.profile.investor_class });
    else state.profile = res.profile;
    state.done.add("rehearse");
    refreshAudit();
    narrateOutcome(res.outcome);
    setTimeout(() => { stage.remove(); go("rehearse"); $("#rehearsalResult")?.scrollIntoView({ behavior: "smooth" }); }, action === "sell" ? 900 : 300);
  };
  $("#thSell").onclick = () => finish("sell", i);
  $("#thBuy").onclick = (e) => { if (boughtAt === null) { boughtAt = i; e.target.textContent = t("Bought more"); e.target.disabled = true; } };
  $("#thQuit").onclick = () => { done = true; clearTimeout(timer); stage.remove(); note(t("Rehearsal stopped. Nothing was recorded about your risk class.")); };
  stage.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#thQuit").click(); });
  timer = setTimeout(tick, pace.start);
}

function resultCard(o) {
  const sold = o.action === "sell";
  const lowered = o.new_class < o.previous_class;
  const gap = o.final_value_if_held - o.final_value_of_choice;
  return `
    <h3>${t("Your rehearsal")}</h3>
    <div class="sheet rehearse-result ${sold ? "sold" : "held"}">
      <p class="rr-head">${sold
        ? t("You sold in {month}, {dd} below your peak.", { month: monthName(o.month), dd: pct(o.drawdown_at_decision) })
        : t("You held through the worst of it: {dd} below your peak in {month}.", { dd: pct(o.max_drawdown), month: monthName(o.trough_month) })}</p>
      <div class="rr-compare">
        <div><span>${t("If you had held to March 2013")}</span><b>${money(o.final_value_if_held)}</b></div>
        <div><span>${t(sold ? "After selling and keeping cash" : o.action === "buy_more" ? "You held, and even bought more" : "What you ended with")}</span><b>${money(o.final_value_of_choice)}</b></div>
        ${sold ? `<div class="rr-gap"><span>${t("Cost of selling")}</span><b>−${money(gap)}</b></div>` : ""}
      </div>
      <p>${lowered
        ? t("Your answers put you at <strong>C{a}</strong>, but your behaviour supports <strong>C{b}</strong>. We have lowered your risk class: a portfolio you can stay with beats one you abandon at the bottom.", { a: o.previous_class, b: o.new_class })
        : sold
          ? t("You sold at a loss your class already allows for, so your risk class stays at <strong>C{n}</strong>.", { n: o.new_class })
          : t("Your behaviour supports your risk class <strong>C{n}</strong>.", { n: o.new_class })}</p>
      ${lowered ? `<div class="actions"><button class="btn" type="button" id="rebuildAtNew">${t("Rebuild my portfolio at C{n}", { n: o.new_class })}</button></div>` : ""}
    </div>`;
}

function wireResult() {
  const b = $("#rebuildAtNew");
  if (b) b.onclick = async () => { b.disabled = true; await loadAllocation(state.allocation.amount, state.profile.investor_class, true); go("portfolio"); };
}

function narrateOutcome(o) {
  const lowered = o.new_class < o.previous_class;
  if (o.action === "sell") {
    say([
      t("You sold in {month}, down {dd} from your peak. Holding would have left you with <strong>{held}</strong> by March 2013; selling left {sold}.", { month: monthName(o.month), dd: pct(o.drawdown_at_decision), held: money(o.final_value_if_held), sold: money(o.final_value_of_choice) }),
      lowered
        ? t("That tells me more than the questionnaire did. I have lowered your risk class to <strong>C{n}</strong> so the portfolio matches how you actually react.", { n: o.new_class })
        : t("Your class already allows for a loss of that size, so it stays the same."),
    ]);
  } else {
    say([
      t("You held through a {dd} fall. By March 2013 the portfolio was worth <strong>{v}</strong>.", { dd: pct(o.max_drawdown), v: money(o.final_value_if_held) }),
      t("Your behaviour supports the risk class from your answers."),
    ]);
  }
}

// ---------------------------------------------------------------- 4. goal

const short = (v) => (v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : `${Math.round(v)}`);
const GOAL_KINDS = ["Buy a home", "Children's education", "Retirement", "Something else"];  // keys; labels via t()

async function renderGoal() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">${t("Building your portfolio…")}</p>`;
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
    <h1>${t("Will you reach your goal?")}</h1>
    <p class="lede">${t("We simulate 5,000 possible futures for your portfolio of {amount} and count how many reach your target. Same inputs always give the same answer.", { amount: money(state.allocation.amount) })}</p>
    <div class="sheet">
      <div class="filters" role="radiogroup" aria-label="${t("Goal")}">
        ${GOAL_KINDS.map((k) => `<label class="chip"><input type="radio" name="gk" value="${esc(k)}" ${k === g.name ? "checked" : ""}><span>${esc(t(k))}</span></label>`).join("")}
      </div>
      <div class="facts">
        <div class="field"><label for="gTarget">${t("Target amount")}</label><input id="gTarget" type="number" min="1000" step="1000" value="${g.target}"></div>
        <div class="field"><label for="gYears">${t("In")} <span class="range-value" id="gYearsV">${t("{n} yrs", { n: g.years })}</span></label><input id="gYears" type="range" min="1" max="40" value="${g.years}"></div>
        <div class="field"><label for="gMonthly">${t("Monthly saving")}</label><input id="gMonthly" type="number" min="0" step="100" value="${g.monthly}"></div>
        <label class="check"><input id="gInfl" type="checkbox" ${g.inflation ? "checked" : ""}> ${t("Target in today's money (2% inflation)")}</label>
      </div>
    </div>
    <div id="goalOut"><p class="empty" style="margin-top:20px">${t("Simulating…")}</p></div>`;
  const read = () => ({
    name: $('input[name="gk"]:checked').value,
    target: +$("#gTarget").value,
    years: +$("#gYears").value,
    monthly: +$("#gMonthly").value,
    inflation: $("#gInfl").checked ? 0.02 : 0,
  });
  let debounce;
  const update = () => { clearTimeout(debounce); debounce = setTimeout(() => runGoal(read()), 250); };
  panel.querySelectorAll('input[name="gk"]').forEach((i) => (i.onchange = update));
  $("#gYears").oninput = (e) => { $("#gYearsV").textContent = t("{n} yrs", { n: e.target.value }); update(); };
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
      <div class="goal-chance">${num(`${chance}%`, prov, t("Share of simulated futures that reach the target"))}</div>
      <div>
        <span class="tone ${tone}">${t(tone === "ok" ? "On track" : tone === "mid" ? "Possible" : "Unlikely")}</span>
        <div class="goal-line">${t("chance of reaching <b>{amount}</b> by {year}", { amount: money(r.target_nominal), year })}</div>
        <div class="hint">${input.inflation ? t("{amount} in today's money, grown by 2% inflation a year.", { amount: money(input.target) }) : t("Nominal target, no inflation adjustment.")}</div>
      </div>
    </div>
    ${r.required_monthly === null ? "" : r.required_monthly <= input.monthly
      ? `<div class="verdict-bar ok"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg><div>${t("<strong>You are on track.</strong> Your saving already gives at least an 80% chance.")}</div></div>`
      : `<div class="verdict-bar nudge"><div>${t("Save <strong>{amount}</strong> a month to reach an 80% chance.", { amount: num(money(r.required_monthly), prov, t("Monthly saving needed for an 80% chance")) })}</div><button class="btn secondary" type="button" id="useMonthly">${t("Use {amount} a month", { amount: money(r.required_monthly) })}</button></div>`}
    <div class="sheet" style="margin-top:16px">
      ${fanChart(r.fan, r.target_nominal)}
      <div class="legend fan-legend">
        <span><i class="band-outer"></i>${t("8 in 10 futures")}</span>
        <span><i class="band-inner"></i>${t("Half of futures")}</span>
        <span><i class="line-median"></i>${t("Median")}</span>
        <span><i class="line-target"></i>${t("Your target")}</span>
      </div>
    </div>
    <div class="kpis" style="margin-top:16px;grid-template-columns:repeat(3,1fr)">
      <div class="kpi"><div class="k">${t("Bad case (1 in 10)")}</div><span class="v">${num(money(r.terminal_p10), prov, t("10th percentile outcome"))}</span></div>
      <div class="kpi"><div class="k">${t("Median outcome")}</div><span class="v">${num(money(r.terminal_p50), prov, t("Median outcome"))}</span></div>
      <div class="kpi"><div class="k">${t("Good case (1 in 10)")}</div><span class="v">${num(money(r.terminal_p90), prov, t("90th percentile outcome"))}</span></div>
    </div>
    <details class="assume"><summary>${t("Assumptions")}</summary><ul>${r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>`;
  const use = $("#useMonthly");
  if (use) use.onclick = () => { $("#gMonthly").value = r.required_monthly; runGoal({ ...input, monthly: r.required_monthly }); };
  wireFan(r.fan, r.target_nominal);
  state.done.add("goal");
  if (!state.goalNarrated) {
    state.goalNarrated = true;
    say([
      t("With {amount} a month, about <strong>{n} in 100</strong> simulated futures reach {target} by {year}.", { amount: money(input.monthly), n: chance, target: money(r.target_nominal), year }),
      r.required_monthly && r.required_monthly > input.monthly
        ? t("Saving {amount} a month would lift that to <strong>80 in 100</strong>. A longer horizon also helps. Taking more risk than your class allows is not an option I can offer.", { amount: money(r.required_monthly) })
        : t("That is a comfortable margin. Keep the plan under review once a year."),
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
      ${fan.filter((_, i) => i % step === 0).map((f) => `<text class="axis" x="${x(f.year)}" y="${H - 8}" text-anchor="middle">${f.year === 0 ? t("Now") : t("{n}y", { n: f.year })}</text>`).join("")}
      <path class="band-outer" d="${area("p10", "p90")}"/>
      <path class="band-inner" d="${area("p25", "p75")}"/>
      <path class="median" d="M${fan.map((f, i) => `${x(i)},${y(f.p50)}`).join("L")}"/>
      <line class="target" x1="${L}" x2="${W - R}" y1="${y(target)}" y2="${y(target)}"/>
      <text class="target-label" x="${L + 8}" y="${y(target) - 7}" text-anchor="start">${t("Target {v}", { v: short(target) })}</text>
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
    tip.innerHTML = `<b>${i === 0 ? t("Today") : t("Year {n}", { n: i })}</b><div>${t("Median {v}", { v: money(f.p50) })}</div><div class="dim">${t("8 in 10 between {a} and {b}", { a: short(f.p10), b: short(f.p90) })}</div>`;
    tip.hidden = false;
    const left = (px / W) * box.width;
    tip.style.left = `${Math.min(box.width - 190, Math.max(0, left + 12))}px`;
    tip.style.top = `${(py / H) * box.height - 20}px`;
  };
  const hide = () => { tip.hidden = true; $("#fanCross").setAttribute("visibility", "hidden"); $("#fanDot").setAttribute("visibility", "hidden"); };
  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerleave", hide);
}

// ---------------------------------------------------------------- 5. compare

async function renderCompare(asset = "") {
  panel.innerHTML = `<p class="empty">${t("Comparing products…")}</p>`;
  let data;
  try { data = await api(`/api/compare${asset ? `?asset_class=${asset}` : ""}`); }
  catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  state.done.add("compare");
  refreshAudit();
  const prov = data.provenance;
  const c = state.client;
  panel.innerHTML = `
    <h1>${t("Compare products")}</h1>
    <p class="lede">${t("Every product you are eligible for, ranked by return per unit of risk after fees. Fee cost shows what fees would take from {amount} over {years} years.", { amount: money(c.amount), years: c.horizon_years })}</p>
    ${dataNote()}
    <div class="filters">
      ${["", ...ASSET_ORDER].map((k) => `<label class="chip"><input type="radio" name="af" value="${k}" ${k === asset ? "checked" : ""}><span>${k ? ASSET_NAMES[k] : t("All")}</span></label>`).join("")}
    </div>
    <div class="sheet">
      ${data.rows.length ? `
      <table>
        <thead><tr><th>${t("Product")}</th><th>${t("Risk")}</th><th class="r">${t("Return after fees")}</th><th class="r">${t("Volatility")}</th><th class="r">${t("Fee")}</th><th class="r">${t("Fee cost")}</th><th class="r">${t("Access")}</th></tr></thead>
        <tbody>
          ${data.rows.map((r) => `
            <tr>
              <td class="prod"><span class="swatch" style="background:var(--${r.asset_class})"></span>${r.source ? `<a class="fund-link" href="${esc(r.source)}" target="_blank" rel="noopener">${esc(r.name)}</a>` : esc(r.name)}<small>${ASSET_NAMES[r.asset_class]}</small></td>
              <td><span class="risk">R${r.risk_class}</span></td>
              <td class="r">${num(pct(r.net_return, 2), prov, t("Expected return after fees: {name}", { name: r.name }))}</td>
              <td class="r">${pct(r.volatility, 1)}</td>
              <td class="r">${pct(r.fee, 2)}</td>
              <td class="r">${num(money(r.fee_drag), prov, t("Fee cost over {years} years: {name}", { years: c.horizon_years, name: r.name }))}</td>
              <td class="r">${r.liquidity_days <= 31 ? tn("1 day", "{n} days", r.liquidity_days) : t("{n} months", { n: Math.round(r.liquidity_days / 30) })}</td>
            </tr>`).join("")}
        </tbody>
      </table>` : `<p class="empty">${t("No products in this group match your risk class.")}</p>`}
    </div>
    ${data.locked?.length ? `<p class="hidden-note">${t("Not shown because you may need the money sooner than they allow withdrawals: {names}.", { names: data.locked.map((h) => esc(h.name)).join(", ") })}</p>` : ""}
    ${data.hidden.length ? `<p class="hidden-note">${t("Not shown because they exceed R{n}: {names}.", { n: state.profile.investor_class, names: data.hidden.map((h) => `${esc(h.name)} (R${h.risk_class})`).join(", ") })}</p>` : ""}`;
  panel.querySelectorAll('input[name="af"]').forEach((i) => (i.onchange = () => renderCompare(i.value)));
}

// ---------------------------------------------------------------- 6. stress

async function renderStress() {
  if (!state.allocation) { await renderPortfolio(); }
  panel.innerHTML = `<p class="empty">${t("Running scenarios…")}</p>`;
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
    <h1>${t("How would this portfolio have fared?")}</h1>
    <p class="lede">${t("We replay three historical shocks on your current portfolio of {amount} and compare the loss with the {limit} you said you could accept.", { amount: money(state.allocation.amount), limit: pct(data.max_loss, 0) })}</p>
    <div class="sheet" style="padding-top:40px">
      ${data.scenarios.map((s, i) => `
        <div class="stress-row">
          <div class="name">${esc(LANG === "zh" ? t(s.name) : s.name[0].toUpperCase() + s.name.slice(1))}</div>
          <div class="stress-track">
            <div class="stress-bar ${s.breach ? "breach" : ""}" style="width:${x(s.loss)}"></div>
            <div class="stress-val" style="left:${x(s.loss)}">−${pct(s.loss)} <span style="font-weight:400;color:var(--ink-3)">(${num(money(s.loss_amount), prov, t("Loss in {name}", { name: t(s.name) }))})</span></div>
            <div class="limit" style="left:${x(data.max_loss)}"></div>
            ${i === 0 ? `<div class="limit-label" style="left:${x(data.max_loss)}">${t("Your limit {v}", { v: pct(data.max_loss, 0) })}</div>` : ""}
          </div>
        </div>`).join("")}
      <div class="verdict-bar ${breaches.length ? "bad" : "ok"}">
        ${breaches.length
          ? `<svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg><div>${t("<strong>Exceeds your limit in {n} of {total} scenarios.</strong> Consider a lower risk level on the Portfolio step.", { n: breaches.length, total: data.scenarios.length })}</div>`
          : `<svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg><div>${t("<strong>Within your limit in every scenario.</strong> The worst case is a {v} fall.", { v: pct(Math.max(...data.scenarios.map((s) => s.loss))) })}</div>`}
      </div>
    </div>
    <p class="hint">${t("Shocks are applied per asset class from historical peak-to-trough moves. Real losses can be larger.")}</p>`;
  const worst = data.scenarios.reduce((a, b) => (b.loss > a.loss ? b : a));
  say([
    t("In a repeat of the {name}, this portfolio would have fallen about <strong>{v}</strong>, or {amount}.", { name: esc(t(worst.name)), v: pct(worst.loss), amount: money(worst.loss_amount) }),
    breaches.length
      ? t("That is more than the {limit} you told me you could accept, so I would not recommend proceeding at this risk level.", { limit: pct(data.max_loss, 0) })
      : t("That stays within the {limit} you told me you could accept.", { limit: pct(data.max_loss, 0) }),
  ]);
}

// ---------------------------------------------------------------- 7. execute

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const shortDate = (iso) => new Date(iso).toLocaleDateString(LOCALE, { day: "numeric", month: "short" });

function setTier(tier) {
  state.tier = tier;
  const el = $(".tier");
  el.textContent = tier.level >= 3 ? t("Simulated trading on") : t("Advice only");
  el.classList.toggle("live", tier.level >= 3);
  el.title = tier.level >= 3
    ? t("You signed the risk disclosure. Orders still need your explicit hold-to-confirm.")
    : t("Permission tier: the advisor can explain and recommend, but cannot place orders.");
}

async function renderExecute() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">${t("Building your portfolio…")}</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, false); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  let tier;
  try { tier = await api("/api/tier"); } catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  setTier(tier);
  if (tier.level < 3) renderDisclosure(tier);
  else renderTicket();
}

function renderDisclosure(tier) {
  const p = state.profile;
  panel.innerHTML = `
    <h1>${t("Before you place orders")}</h1>
    <p class="lede">${t("Orders run on a simulated brokerage account. Read the risks below and sign to switch this session from advice only to simulated trading. You will still confirm every order yourself.")}</p>
    <div class="sheet disclosure">
      <h3 style="margin-top:0">${t("Risk disclosure")}</h3>
      <ul class="reasons">
        <li>${t("Investments can fall in value and you may get back less than you invest.")}</li>
        <li>${t("Expected returns and stress tests are model estimates. Past performance does not predict future results.")}</li>
        <li>${t("Your risk class is C{n}. Products above R{n} are blocked for you.", { n: p.investor_class })}</li>
        <li>${t("Products rated R4 or higher have a cooling-off period before they can be bought.")}</li>
        <li>${t("The AI advisor can never place or confirm an order on your behalf.")}</li>
      </ul>
      ${tier.kill_switch ? `<div class="verdict-bar bad"><div>${t("<strong>Trading is switched off for all sessions right now.</strong> You can still use every advice step.")}</div></div>` : `
      <form id="consent" class="sign">
        <label class="check" style="padding-top:18px"><input type="checkbox" id="accept"> ${t("I have read and understood these risks")}</label>
        <div class="field sign-field">
          <label for="signName">${t("Sign with your full name")}</label>
          <input id="signName" type="text" autocomplete="name" placeholder="${t("Your full name")}" maxlength="80">
          <div class="signature" aria-hidden="true"><span id="sigInk"></span></div>
        </div>
        <div class="actions"><button class="btn" id="signBtn" type="submit" disabled>${t("Sign and enable simulated trading")}</button></div>
        <div id="consentErr"></div>
      </form>`}
    </div>`;
  if (tier.kill_switch) return;
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
      say([t("Thank you. Simulated trading is now enabled for this session."), t("I have prepared an order ticket from your portfolio. Nothing is placed until you hold the confirm button yourself.")]);
      renderTicket();
    } catch (err) {
      $("#consentErr").innerHTML = `<p class="err">${esc(err.message)}</p>`;
      $("#signBtn").disabled = false;
    }
  };
}

async function renderTicket() {
  if (staleBanner()) {
    panel.innerHTML = `<h1>${t("Review and confirm")}</h1><p class="lede">${t("Your risk class changed after this portfolio was built.")}</p>${staleBanner()}`;
    wireStale();
    return;
  }
  panel.innerHTML = `<p class="empty">${t("Preparing your order ticket…")}</p>`;
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
    <h1>${t("Review and confirm")}</h1>
    <p class="lede">${t("These orders match your recommended portfolio exactly. Every line passed the suitability, liquidity and limit checks on the server.")}</p>
    ${state.rehearsal ? "" : `<div class="verdict-bar nudge"><div>${t("<strong>You haven't rehearsed a crash with this portfolio yet.</strong> Most people who sell at the bottom never expected to.")}</div><button class="btn secondary" type="button" id="goRehearse">${t("Rehearse first")}</button></div>`}
    <div class="exec">
      <div class="ticket">
        <div class="ticket-head">
          <div><div class="ticket-sub">${t("Order ticket")}</div><div class="ticket-title">${tn("Buy 1 product", "Buy {n} products", d.orders.length)}</div></div>
          <div class="ticket-acct"><div class="ticket-sub">${t("Simulated cash")}</div><b>${num(money(d.cash), d.provenance, t("Simulated account cash"))}</b></div>
        </div>
        <div class="perf" aria-hidden="true"></div>
        <ul class="ticket-lines">
          ${d.orders.map((o) => `
            <li class="${o.cooling_off ? "muted" : ""}">
              <span class="swatch" style="background:var(--${o.asset_class})"></span>
              <span class="tl-name">${esc(o.name)}<small>R${o.risk_class} · ${t("{units} units at {nav}", { units: o.units.toFixed(2), nav: o.nav.toFixed(2) })}${o.cooling_off ? ` · ${t("cooling-off until {date}", { date: shortDate(o.cooling_off_until) })}` : ""}</small></span>
              <span class="tl-amt">${money(o.amount)}</span>
            </li>`).join("")}
        </ul>
        <div class="perf" aria-hidden="true"></div>
        <ul class="checks">
          <li>${t("Every product is rated R{n} or lower", { n: d.investor_class })}</li>
          <li class="${state.rehearsal ? "" : "todo"}">${state.rehearsal ? t(state.rehearsal.action === "sell" ? "Crash rehearsal completed: sold in 2008" : "Crash rehearsal completed: held in 2008") : t("Crash rehearsal not taken yet")}</li>
          <li>${t("Per-order and daily limits respected")}</li>
          <li>${t("Risk profile valid until {date}", { date: longDate(state.profile.expires_on) })}</li>
        </ul>
        <div class="ticket-total"><span>${t(later.length ? "Placed now" : "Total")}</span><b>${money(total)}</b></div>
      </div>

      <div class="confirm-zone">
        ${now.length ? `
        <button class="hold" id="hold" type="button" aria-describedby="holdHint">
          <span class="hold-label">${tn("Hold to place 1 order", "Hold to place {n} orders", now.length)}</span>
          <span class="hold-fill" aria-hidden="true">${tn("Hold to place 1 order", "Hold to place {n} orders", now.length)}</span>
        </button>
        <p class="hint" id="holdHint">${t("Press and hold for 1.5 seconds. You can undo for 5 seconds afterwards.")}</p>` : `<p class="empty">${t("All orders are in their cooling-off period.")}</p>`}
        <div id="execErr"></div>
        <div class="printer" id="printer" hidden>
          <div class="slot" aria-hidden="true"></div>
          <div class="paper-wrap"><div class="paper" id="paper"></div></div>
        </div>
      </div>
    </div>`;
  if (now.length) wireHold($("#hold"), now);
  const gr = $("#goRehearse");
  if (gr) gr.onclick = () => go("rehearse");
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
    undo.innerHTML = `<span>${t('Placing orders in <b id="undoN">{n}</b> s', { n: left })}</span><button type="button" class="btn secondary" id="undoBtn">${t("Undo")}</button>`;
    btn.hidden = true;
    $("#holdHint").hidden = true;
    zone.prepend(undo);
    $("#undoBtn").focus();
    const timer = setInterval(async () => {
      left -= 1;
      if (left > 0) { $("#undoN").textContent = left; return; }
      clearInterval(timer);
      undo.innerHTML = `<span>${t("Placing orders…")}</span>`;
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
      note(t("Orders cancelled before they were sent. Nothing was placed."));
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
    <div class="rc-head">${t("Wealth Advisor")}<br>${t("Simulated brokerage account")}</div>
    <div class="rc-center">${t("Trade confirmation")}</div>
    <div class="rc-center rc-dim">${ts.toLocaleDateString(LOCALE, { day: "2-digit", month: "short", year: "numeric" })} ${ts.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" })}</div>
    <div class="rc-rule"></div>
    ${r.executed.map((o) => `
      <div class="rc-item">
        ${line(t("BUY {name}", { name: esc(o.name) }), "")}
        ${line(`&nbsp;&nbsp;R${o.risk_class} · ${o.units.toFixed(2)} u @ ${o.nav.toFixed(2)}`, money(o.amount))}
      </div>`).join("")}
    ${later.map((o) => `
      <div class="rc-item rc-dim">
        ${line(t("HOLD {name}", { name: esc(o.name) }), "")}
        ${line(`&nbsp;&nbsp;${t("cooling-off until {date}", { date: shortDate(o.cooling_off_until) })}`, money(o.amount))}
      </div>`).join("")}
    ${r.failed.map((f) => `<div class="rc-item rc-fail">${line(t("NOT PLACED {id}", { id: esc(f.order_id) }), "")}<div>&nbsp;&nbsp;${esc(f.reason)}</div></div>`).join("")}
    <div class="rc-rule"></div>
    ${line(`<b>${t("Total executed")}</b>`, `<b>${money(r.total)}</b>`)}
    ${line(t("Cash remaining"), money(r.cash))}
    ${settle ? line(t("Settlement"), `T+2 · ${shortDate(settle)}`) : ""}
    <div class="rc-rule"></div>
    <div class="rc-dim">${t("Audit record")}</div>
    <div class="rc-hash">${r.provenance.audit_hash.match(/.{1,4}/g).slice(0, 8).join(" ")}</div>
    ${barcode(r.provenance.audit_hash)}
    <div class="stamp" aria-label="${t("Suitability checked")}">
      <span>${t("Suitability checked")}</span>
      <b>${t("C{n} · all ≤ R{n}", { n: r.investor_class })}</b>
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
      ? tn("Done. 1 order for <strong>{amount}</strong> was placed on your simulated account and will settle in two business days.", "Done. {n} orders for <strong>{amount}</strong> were placed on your simulated account and will settle in two business days.", r.executed.length, { amount: money(r.total) })
      : t("No orders were placed."),
    ...(later.length ? [tn("1 higher-risk order is held for the cooling-off period, as the rules require.", "{n} higher-risk orders are held for the cooling-off period, as the rules require.", later.length)] : []),
    t("The confirmation carries the audit-record hash, so this trade can be verified later."),
  ]);
}

async function anchorOnReceipt(paper) {
  const slot = document.createElement("div");
  slot.className = "rc-chain";
  slot.innerHTML = `<div class="rc-rule"></div><div class="rc-dim">${t("On-chain proof")}</div><div>${t("Anchoring on Ethereum Sepolia…")}</div>`;
  paper.insertBefore(slot, paper.querySelector(".stamp"));
  try {
    const a = await api("/api/anchor", { method: "POST" });
    slot.lastElementChild.innerHTML = a.sent
      ? `Ethereum Sepolia · <a href="${esc(a.explorer_url)}" target="_blank" rel="noopener">${esc(a.tx_hash.slice(0, 10))}…${esc(a.tx_hash.slice(-6))}</a><br><span class="rc-dim">${t("audit head after {n} records", { n: a.record_count })}</span>`
      : `<span class="rc-dim">${t("Not anchored: {why}", { why: esc(a.note) })}</span>`;
    refreshAudit();
  } catch (err) {
    slot.lastElementChild.innerHTML = `<span class="rc-dim">${t("Not anchored: {why}", { why: esc(err.message) })}</span>`;
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
    $("#auditText").textContent = a.valid ? t("Audit chain verified · {n}", { n: a.total }) : t("Audit chain broken");
    return a;
  } catch { return null; }
}
async function openDrawer() {
  lastFocus = document.activeElement;
  const a = await refreshAudit();
  if (!a) return;
  $("#drawerStatus").textContent = a.valid
    ? t("{n} records. Each one includes the hash of the record before it, so editing any past entry breaks the chain.", { n: a.total })
    : t("Verification failed: {why}", { why: a.reason });
  renderAnchors();
  $("#chain").innerHTML = a.records.map((r) => `
    <li>
      <div class="ev">${esc(r.event.replace(/_/g, " "))}</div>
      <div class="src">${esc(new Date(r.timestamp).toLocaleString(LOCALE))}${r.source ? ` · ${esc(r.source)}` : ""}</div>
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
      <div><b>${t("Blockchain anchors")}</b><div class="hint">${sent.length ? t("{n} on Ethereum Sepolia", { n: sent.length }) : t("Write the current chain head to a public blockchain.")}</div></div>
      <button class="btn secondary" type="button" id="anchorNow">${t("Anchor now")}</button>
    </div>
    ${sent.slice().reverse().map((x) => `
      <div class="anchor-row">
        <a href="${esc(x.explorer_url)}" target="_blank" rel="noopener">${esc(x.tx_hash.slice(0, 12))}…</a>
        <span class="rc-dim">${t("{n} records", { n: x.record_count })}</span>
        <button class="why" type="button" data-verify="${esc(x.tx_hash)}">${t("Verify")}</button>
        <span class="verify-out"></span>
      </div>`).join("")}
    ${list.length && !sent.length ? `<p class="hint">${t("Last attempt: {why}", { why: esc(list[list.length - 1].note) })}</p>` : ""}`;
  $("#anchorNow").onclick = async (e) => {
    e.target.disabled = true;
    try { await api("/api/anchor", { method: "POST" }); } catch (err) { note(err.message, "msg-error"); }
    await openDrawer();
  };
  box.querySelectorAll("[data-verify]").forEach((b) => (b.onclick = async () => {
    const out = b.nextElementSibling;
    out.textContent = t("Checking…");
    try {
      const v = await api(`/api/anchor/verify?tx=${b.dataset.verify}`);
      out.textContent = v.matches ? t("✓ matches the log at record {n}, block {b}", { n: v.record_count, b: v.block }) : t("✗ does not match ({why})", { why: v.chain_reason });
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
    t("Hello. I'm your digital wealth advisor."),
    t("Before I recommend anything, I need to understand how much risk you can afford and how much you are comfortable with. The short questionnaire on the right takes about two minutes."),
    t("You can also ask me anything here at any time."),
  ]);
  try { state.catalog = await api("/api/catalog-info"); } catch { state.catalog = null; }
  try {
    state.questionnaire = await api("/api/questionnaire");
  } catch (err) {
    panel.innerHTML = `<p class="err">${t("Could not load the questionnaire: {err}", { err: esc(err.message) })}</p>`;
    return;
  }
  try {
    const restored = await api("/api/state");
    applyServerState(restored);
    if (restored.profile) note(t("Welcome back. Your client file from this session is restored."));
  } catch { /* a fresh session simply starts at step 1 */ }
  go(state.profile ? (state.allocation ? "portfolio" : "profile") : "profile");
  refreshAudit();
})();
