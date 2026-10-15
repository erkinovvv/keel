// Keel web UI. Every number shown is computed on the server by deterministic code;
// the UI only formats it and shows where it came from (provenance popover).

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const longDate = (iso) => new Date(iso).toLocaleDateString(LOCALE, { day: "numeric", month: "short", year: "numeric" });
const money = (v) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
const ASSET_ORDER = ["cash", "bonds", "equity", "gold", "reits"];
const ASSET_NAMES = ASSET_NAMES_I18N[LANG];
const LEVEL = LEVEL_NAMES_I18N[LANG];
const RISK = RISK_NAMES_I18N[LANG];
// "Aggressive (5 of 5)"
const levelText = (n) => t("{name} ({n} of 5)", { name: LEVEL[n], n });

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
      <dt>${t("Calculated by")}</dt><dd>${esc(p.source)}()</dd>
      <dt>${t("Record")}</dt><dd>${esc(p.audit_hash.slice(0, 16))}…</dd>
      <dt>${t("Saved at")}</dt><dd>${esc(new Date(p.timestamp).toLocaleTimeString(LOCALE))}</dd>
    </dl>`;
  popover.hidden = false;
  const r = btn.getBoundingClientRect();
  const left = Math.min(window.innerWidth - 316, Math.max(16, r.left));
  const top = r.bottom + 8 + 150 > window.innerHeight ? r.top - popover.offsetHeight - 8 : r.bottom + 8;
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  popover.hidden = true;
  if (document.body.classList.contains("chat-open")) closeChat(); else closeDrawer();
});

// ---------------------------------------------------------------- advisor thread

const thread = $("#thread");
function say(paragraphs) {
  const li = document.createElement("li");
  li.className = "msg-advisor";
  li.innerHTML = `${paragraphs.map((p) => `<p>${p}</p>`).join("")}`;
  thread.append(li);
  thread.scrollTop = thread.scrollHeight;
  notifyChat(li);
}

// On phones the chat is a full-screen sheet; while it is closed, new advisor messages show as a
// short preview under the top bar and a count on the chat button.
const phone = window.matchMedia("(max-width: 920px)");
const toast = $("#toast");
let unread = 0, toastTimer;
function notifyChat(li) {
  if (!phone.matches || document.body.classList.contains("chat-open")) return;
  unread += 1;
  $("#chatBadge").textContent = unread;
  $("#chatBadge").hidden = false;
  toast.innerHTML = `<span class="avatar" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M8 13h16M16 13v11M12.5 24h7"/></svg></span><span><b>${t("Your advisor")}</b>${esc([...li.querySelectorAll("p")].map((x) => x.textContent).join(" ").replace(/\s+/g, " ").trim())}</span>`;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), 6000);
}
function openChat() {
  document.body.classList.add("chat-open");
  $("#chatBtn").setAttribute("aria-expanded", "true");
  unread = 0;
  $("#chatBadge").hidden = true;
  toast.hidden = true;
  thread.scrollTop = thread.scrollHeight;
}
function closeChat() {
  document.body.classList.remove("chat-open");
  $("#chatBtn").setAttribute("aria-expanded", "false");
  $("#chatBtn").focus();
}
$("#chatBtn").onclick = openChat;
$("#advisorClose").onclick = closeChat;
toast.onclick = openChat;
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
    changes.push(t("risk level {level}", { level: LEVEL[s.profile.investor_class] }));
  }
  if (s.client && JSON.stringify(s.client) !== JSON.stringify(state.client)) {
    if (state.client && fromChat) changes.push(t("your details"));
    state.client = { amount: 100000, horizon_years: 10, max_loss: 0.2, age: 35, ...Object.fromEntries(Object.entries(s.client).filter(([, v]) => v !== null)) };
  }
  if (s.allocation_id && s.allocation_id !== state.allocationId) {
    Object.assign(state, { allocation: s.allocation, allocationId: s.allocation_id, allocationProv: s.allocation_provenance, allocationLevel: s.allocation.investor_class, drafts: null });
    state.done.add("portfolio");
    changes.push(t("your plan"));
  }
  if (s.tier) setTier(s.tier);
  if (s.goal && JSON.stringify(s.goal.input) !== JSON.stringify(state.goalInput)) {
    state.goalInput = s.goal.input;
    changes.push(t("Goal"));
  }
  if (fromChat && changes.length) {
    note(t("Updated from our chat: {changes}.", { changes: changes.join(LANG === "zh" ? "、" : ", ") }), "msg-sync");
    for (const b of steps.querySelectorAll("button")) b.disabled = b.dataset.step !== "profile" && !state.profile;
    const affected = { profile: Boolean(s.profile), portfolio: changes.includes(t("your plan")), goal: Boolean(s.goal) };
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
      bubble.firstChild.textContent = r.redacted;
      const tag = document.createElement("small");
      tag.className = "pii-tag";
      tag.textContent = t("Hidden from the AI for your privacy: {types}", { types: r.pii_types.map((x) => x.toLowerCase().replace(/_/g, " ")).join(", ") });
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
    say(chatHtml(res.reply));
    applyServerState(res.state, { fromChat: true });
  } catch (err) {
    typing.remove();
    note(err.message, "msg-error");
  } finally {
    send.disabled = false;
    refreshAudit();
  }
});
// Model text is escaped first; only **bold** and line breaks are turned back into markup.
function chatHtml(text) {
  return esc(text).split(/\n{2,}/).map((p) => p.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*\*/g, "").replace(/\n/g, "<br>"));
}
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
// One obvious next action per step; Compare and Stress test are optional tools off the main path.
function nextBar(step, label, { back = false } = {}) {
  return `<div class="actions next-bar">${back ? `<button class="btn secondary" type="button" data-go="portfolio">${t("Back to my plan")}</button>` : ""}${step ? `<button class="btn" type="button" data-go="${step}">${label}</button>` : ""}</div>`;
}
panel.addEventListener("click", (e) => {
  const b = e.target.closest("[data-go]");
  if (b) go(b.dataset.go);
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
  if (phone.matches) window.scrollTo(0, 0);
}

const CURRENCY_SIGN = { CNY: "¥", USD: "$", EUR: "€", HKD: "HK$" };
const currency = () => state.catalog?.currency || "";

// ---------------------------------------------------------------- 1. profile

// Years used for goal planning, from the horizon answer (the goal step lets the client adjust it).
const HORIZON_YEARS = { under_1y: 1, "1_3y": 2, "3_7y": 5, "7_10y": 8, over_10y: 15 };

function renderProfile() {
  const c = state.client || { amount: 100000, horizon_years: 10, max_loss: 0.2, age: 35 };
  const prev = state.answers || {};
  // Once assessed, the result leads and the questionnaire stays below for changes.
  const assessed = Boolean(state.profile);
  panel.innerHTML = `
    <h1>${t("Let's get to know you")}</h1>
    <p class="lede">${t("Answer 8 short questions. They tell us how much risk is right for you. Your answers stay private.")}</p>
    ${assessed ? `<div id="profileResult"></div><h3 class="change-head">${t("Change your answers")}</h3>` : ""}
    <form id="kyc">
      <h3>${t("About you")}</h3>
      <div class="sheet">
        <div class="facts">
          <div class="field"><label for="age">${t("Age")}</label><input id="age" type="number" inputmode="numeric" min="18" max="100" value="${c.age}" required></div>
          <div class="field"><label for="amount">${t("How much do you want to invest?")}</label><div class="affix"><input id="amount" type="number" inputmode="numeric" min="1000" step="1000" value="${c.amount}" required>${currency() ? `<span>${esc(currency())}</span>` : ""}</div></div>
          <div class="field"><label for="maxloss">${t("The most you could lose in a bad year and stay calm")} <span class="range-value" id="maxlossV">${Math.round(c.max_loss * 100)}%</span></label><input id="maxloss" type="range" min="5" max="50" value="${Math.round(c.max_loss * 100)}"></div>
          <label class="check"><input id="borrowed" type="checkbox"> ${t("Some of this money is borrowed")}</label>
        </div>
      </div>
      <h3>${t("Your answers")}</h3>
      <div class="questions">
        ${state.questionnaire.map((q, n) => `
          <fieldset class="q">
            <legend data-missing="${t("Answer this question")}"><span class="qn">${n + 1}/${state.questionnaire.length}</span><span>${esc(q.question)}</span></legend>
            <div class="chips">
              ${q.options.map((o) => `
                <label class="chip"><input type="radio" name="${q.key}" value="${o.key}" ${prev[q.key] === o.key ? "checked" : ""}><span>${esc(o.label)}</span></label>`).join("")}
            </div>
          </fieldset>`).join("")}
      </div>
      <div class="actions submit-bar ${assessed ? "static" : ""}">
        <div class="qprog"><span class="hint" id="answered"></span><div class="qbar" aria-hidden="true"><i id="qbarFill"></i></div></div>
        <button class="btn" type="submit" id="assess">${t("Show my risk level")}</button>
      </div>
      <div id="kycErr"></div>
    </form>
    ${assessed ? "" : `<div id="profileResult"></div>`}`;
  const progress = () => {
    const total = state.questionnaire.length;
    const left = state.questionnaire.filter((q) => !$(`input[name="${q.key}"]:checked`)).length;
    $("#answered").textContent = left ? tn("1 question left", "{n} questions left", left) : t("All done. Your level is worked out by fixed rules, not by AI.");
    $("#qbarFill").style.width = `${((total - left) / total) * 100}%`;
  };
  $("#kyc").addEventListener("change", (e) => {
    progress();
    const q = e.target.closest(".q");
    if (q) q.classList.remove("missing");
  });
  progress();
  $("#maxloss").oninput = (e) => ($("#maxlossV").textContent = `${e.target.value}%`);
  $("#kyc").onsubmit = submitProfile;
  if (state.profile) showProfile(false);
}

async function submitProfile(e) {
  e.preventDefault();
  const missing = state.questionnaire.filter((q) => !$(`input[name="${q.key}"]:checked`));
  if (missing.length) {
    missing.forEach((q) => $(`input[name="${q.key}"]`).closest(".q").classList.add("missing"));
    $(`input[name="${missing[0].key}"]`).closest(".q").scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
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
        horizon_years: HORIZON_YEARS[answers.horizon],
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
  $("#profileResult").innerHTML = `
    <h3 style="margin-top:0">${t("Your risk level")}</h3>
    <div class="sheet">
      <div class="verdict">
        <div>
          <div class="verdict-main">
            <div class="class-badge">${num(`${p.investor_class}`, prov, t("Your risk level"))}</div>
            <div><div class="class-code">${t("Level {n} of 5", { n: p.investor_class })}</div><div class="class-name">${esc(LEVEL[p.investor_class])}</div></div>
          </div>
          <p>${t("We will only suggest funds that are this risky or safer.")}</p>
        </div>
        <div class="scale" aria-label="${esc(levelText(p.investor_class))}">
          <div class="scale-track">${[1, 2, 3, 4, 5].map((i) => `<div class="${i <= p.investor_class ? "on" : ""}"></div>`).join("")}</div>
          <div class="scale-ends"><span>${t("Safer")}</span><span>${t("Riskier")}</span></div>
        </div>
      </div>
      ${p.capacity_class !== p.tolerance_class ? `<p class="two-sides">${t(p.capacity_class < p.tolerance_class ? "You are comfortable with more risk ({t}), but your money situation supports less ({c}). To be safe we use the lower one." : "Your money situation could take more risk ({c}), but you are comfortable with less ({t}). To be safe we use the lower one.", { c: LEVEL[p.capacity_class], t: LEVEL[p.tolerance_class] })}</p>` : ""}
      ${p.flags.map((f) => `<div class="flag"><svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg>${esc(f.text)}</div>`).join("")}
    </div>
    <h3>${t("Why this level")}</h3>
    <div class="sheet"><ul class="reasons">${p.reasons.map((r) => `<li>${esc(r.text)}</li>`).join("")}</ul></div>
    <div class="actions next-bar"><button class="btn" id="toPortfolio" type="button">${t("See my investment plan")}</button></div>`;
  $("#toPortfolio").onclick = () => go("portfolio");
  if (narrate) {
    say([
      t("Your risk level is <strong>{level}</strong>.", { level: esc(levelText(p.investor_class)) }),
      p.capacity_class === p.tolerance_class
        ? t("Both your money situation and your feelings about risk point to the same level.")
        : t("Your money situation and your feelings about risk point to different levels, so I use the lower one to keep you safe."),
      ...(p.flags.length ? [esc(p.flags.map((f) => f.text).join(" "))] : []),
      t("From now on I will only suggest funds at this level of risk or safer."),
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
      t("After fees it may grow about <strong>{ret}</strong> a year. In a normal year it can move up or down by about {vol}. These are estimates, not promises.", { ret: pct(a.expected_return), vol: pct(a.volatility) }),
      t("Tap any underlined number to see how it was calculated."),
      t("Before any money moves, try the 2008 crash test with this plan. It takes 90 seconds."),
    ]);
  }
}

// Asset mix as a ring: one arc per asset class with a small gap between arcs.
function donut(parts, funds) {
  const r = 70, c = 2 * Math.PI * r, gap = parts.length > 1 ? 3 : 0;
  let offset = 0;
  const arcs = parts.map(([k, w]) => {
    const len = Math.max(0, w * c - gap);
    const arc = `<circle r="${r}" cx="90" cy="90" stroke="var(--${k})" stroke-dasharray="${len.toFixed(2)} ${(c - len).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}"/>`;
    offset += w * c;
    return arc;
  }).join("");
  return `<div class="donut" role="img" aria-label="${parts.map(([k, w]) => `${ASSET_NAMES[k]} ${pct(w, 0)}`).join(", ")}"><svg viewBox="0 0 180 180">${arcs}</svg><div class="donut-center"><b>${funds}</b><span>${tn("fund", "funds", funds)}</span></div></div>`;
}

function limitNote(a) {
  if (a.stress_limit_before == null || a.stress_limit_after == null) return "";
  const limit = state.client?.max_loss;
  const text = limit != null
    ? t("You said you could lose at most {limit} in a bad year, so we made this plan safer. In the worst crisis of the past it would have lost {after} instead of {before}.", { limit: pct(limit, 0), before: pct(a.stress_limit_before), after: pct(a.stress_limit_after) })
    : t("We made this plan safer. In the worst crisis of the past it would have lost {after} instead of {before}.", { before: pct(a.stress_limit_before), after: pct(a.stress_limit_after) });
  return `<div class="verdict-bar ok limit-note"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg><div>${text}</div></div>`;
}

function dataNote() {
  const c = state.catalog;
  if (!c?.real) return "";
  return `<p class="data-note">${t("These are real Chinese funds. Prices from {date}.", { date: longDate(c.as_of) })}</p>`;
}

function chainName(net = state.catalog?.anchor_network, short = false) {
  if (net !== "fisco") return "Ethereum Sepolia";
  return short ? "FISCO BCOS (WeBank)" : t("WeBank FISCO BCOS consortium chain");
}

function staleBanner() {
  const a = state.allocation, p = state.profile;
  if (!a || !p || a.investor_class <= p.investor_class) return "";
  return `<div class="verdict-bar bad stale"><svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg><div><strong>${t("This plan was made for a riskier level than yours now.")}</strong> ${t("Please update it before you invest.")}</div><button class="btn" type="button" data-rebuild>${t("Update my plan")}</button></div>`;
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
    panel.innerHTML = `<p class="empty">${t("Making your plan…")}</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, true); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  const a = state.allocation;
  const prov = state.allocationProv;
  const mix = ASSET_ORDER.filter((k) => a.by_asset_class[k]);
  panel.innerHTML = `
    <h1>${t("Your investment plan")}</h1>
    <p class="lede">${t("Here is how we suggest splitting your money. Every fund fits your risk level, and no single fund gets more than about a third.")}</p>
    ${staleBanner()}
    ${limitNote(a)}
    <div id="alertSlot">${state.alert ? alertCard(state.alert) : ""}</div>
    <div class="hero">
      <div class="hero-label">${t("You invest")}</div>
      <div class="hero-amount">${CURRENCY_SIGN[currency()] ? `<small>${CURRENCY_SIGN[currency()]}</small>` : ""}${money(a.amount)}</div>
      <div class="hero-chips">
        <span>${t("Risk level: {level}", { level: esc(levelText(a.investor_class)) })}</span>
        <span>${tn("1 fund", "{n} funds", a.holdings.length)}</span>
        ${state.catalog?.real ? `<span>${t("Real funds, prices from {date}", { date: longDate(state.catalog.as_of) })}</span>` : ""}
      </div>
    </div>

    <div class="kpis">
      <div class="kpi"><div class="k">${t("May grow each year")}</div><span class="v">${num(pct(a.expected_return, 1), prov, t("Expected growth a year, after fees"))}</span></div>
      <div class="kpi"><div class="k">${t("Normal ups and downs")}</div><span class="v">±${num(pct(a.volatility, 1), prov, t("Typical move up or down in a year"))}</span></div>
      <div class="kpi"><div class="k">${t("Fund fees each year")}</div><span class="v">${num(pct(a.fee, 2), prov, t("Average fund fee a year"))}</span></div>
      <div class="kpi"><div class="k">${t("Could lose in a bad year")}</div><span class="v">${num(money(a.var_95_1y), prov, t("Loss in a bad year (1 year in 20)"))}</span></div>
    </div>
    <p class="kpi-note">${t("These are estimates, not promises. About 1 year in 20 could be even worse than the bad-year figure.")}</p>

    <h3>${t("How your money is split")}</h3>
    <div class="sheet alloc">
      ${donut(mix.map((k) => [k, a.by_asset_class[k]]), a.holdings.length)}
      <ul class="alloc-legend">
        ${mix.map((k) => `<li><i style="background:var(--${k})"></i><span>${ASSET_NAMES[k]}</span><b>${pct(a.by_asset_class[k], 0)}</b><span>${money(a.amount * a.by_asset_class[k])}</span></li>`).join("")}
      </ul>
    </div>

    <h3>${t("Your funds")}</h3>
    <div class="sheet list">
      ${a.holdings.map((h, i) => `
        <div class="list-item">
          <span class="li-icon" style="--c:var(--${h.asset_class})" aria-hidden="true">${h.kind && h.kind !== "fund" ? KIND_ICON[h.kind === "savings_bond" ? "bond" : "bank"] : esc(ASSET_NAMES[h.asset_class].slice(0, 1))}</span>
          <div>
            <div class="li-name">${esc(h.name)}</div>
            <div class="li-sub">${h.kind && h.kind !== "fund"
              ? `${t(KIND_NAMES[h.kind])} · ${termText(h.term_months)} · ${t("{rate} a year", { rate: pct(h.rate, 2) })}`
              : `${ASSET_NAMES[h.asset_class]} · ${RISK[h.risk_class]}`} · ${num(pct(h.weight, 0), prov, t("Share of your money in {name}", { name: h.name }))}<span class="li-today" data-today="${esc(h.product_id)}"></span></div>
          </div>
          <div class="li-right">
            <div class="li-amt">${num(money(h.amount), prov, t("Amount in {name}", { name: h.name }))}</div>
            <button class="why" type="button" data-why="${i}" aria-expanded="false">${t("Why this?")}</button>
          </div>
        </div>
        <div class="why-row" id="why${i}" hidden><ul>${h.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}${h.source ? `<li><a href="${esc(h.source)}" target="_blank" rel="noopener">${t("Open the fund's page")}</a></li>` : ""}</ul></div>`).join("")}
    </div>
    <h3>${t("Try other numbers")}</h3>
    <div class="sheet whatif">
      <div class="field"><label for="wiAmount">${t("A different amount")}</label><input id="wiAmount" type="number" min="1000" step="1000" value="${a.amount}"></div>
      <div class="field">
        <span class="label">${t("Less risk")}</span>
        <div class="seg" role="group" aria-label="${t("Risk level")}">
          ${[1, 2, 3, 4, 5].map((i) => `<button type="button" data-level="${i}" class="${i === a.investor_class ? "on" : ""}" ${i > p.investor_class ? `disabled title="${t("Riskier than your level")}"` : ""}>${i}</button>`).join("")}
        </div>
        <div class="hint">${t("1 is the safest. Levels riskier than yours are locked.")}</div>
      </div>
    </div>
    ${nextBar("rehearse", t("Next: test this plan in the 2008 crash"))}
    <h3>${t("Markets today")}</h3>
    <div class="sheet markets" id="markets"><p class="empty">${t("Loading prices…")}</p></div>
    <h3>${t("After you invest")}</h3>
    <div class="sheet monitor">
      <p class="hint" style="margin-top:0">${t("We watch the markets for you and message you first when something big happens.")}</p>
      <div class="actions" style="margin-top:12px"><button class="btn" type="button" id="checkLive">${t("Check my plan with today's prices")}</button></div>
      <p class="hint" style="margin:18px 0 0">${t("Or see what we would do in a big move:")}</p>
      <div class="filters">${Object.entries(MARKET_EVENTS).map(([k, label]) => `<button class="btn secondary" type="button" data-event="${k}">${t(label)}</button>`).join("")}</div>
    </div>
    <div id="allocErr"></div>`;

  panel.querySelectorAll("[data-why]").forEach((b) => (b.onclick = () => {
    const row = $(`#why${b.dataset.why}`);
    row.hidden = !row.hidden;
    b.setAttribute("aria-expanded", String(!row.hidden));
  }));
  panel.querySelectorAll("[data-level]").forEach((b) => (b.onclick = () => rebuild(+$("#wiAmount").value, +b.dataset.level)));
  let debounce;
  $("#wiAmount").oninput = (e) => { clearTimeout(debounce); debounce = setTimeout(() => rebuild(+e.target.value, state.allocationLevel), 450); };
  panel.querySelectorAll("[data-event]").forEach((b) => (b.onclick = () => triggerMarket(b.dataset.event)));
  $("#checkLive").onclick = () => triggerMarket("live_nav", "/api/market/check-live");
  loadMarkets();
  loadFundsToday();
  wireAlert();
  wireStale();
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

// ---------------------------------------------------------------- proactive monitoring

const MARKET_EVENTS = { equity_selloff: "Stock markets crash", rate_shock: "Interest rates jump", rally: "Stock markets jump" };
const eventLabel = (c) => t(c.event === "live_nav" ? "Today's real prices" : MARKET_EVENTS[c.event] || c.event_name);
const SOURCE_NAMES = { sina: "Sina Finance", tencent: "Tencent Finance", yahoo: "Yahoo Finance", eastmoney: "East Money" };

// Live index, gold, currency and bond-yield quotes; falls back to the dated snapshot, said plainly.
async function loadMarkets() {
  const box = $("#markets");
  if (!box) return;
  let data;
  try { data = await api("/api/market/live"); } catch { box.innerHTML = `<p class="empty">${t("Prices are not available right now.")}</p>`; return; }
  const quotes = data.quotes || [];
  const live = quotes.filter((q) => !q.stale);
  const sources = [...new Set(live.map((q) => t(SOURCE_NAMES[q.source] || q.source)))].join(LANG === "zh" ? "、" : ", ");
  const status = live.length
    ? t("Live prices from {sources}, {time}.", { sources, time: new Date().toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" }) })
    : t("Live prices are not available right now. Showing saved prices from {date}.", { date: longDate(quotes[0]?.as_of || new Date().toISOString()) });
  const price = (q) => (q.id === "cn10y" ? `${q.price.toFixed(2)}%` : q.price >= 1000 ? money(q.price) : q.price.toFixed(q.price < 10 ? 4 : 2));
  box.innerHTML = `
    <div class="quotes">${quotes.map((q) => `
      <div class="quote">
        <span class="q-name">${esc(LANG === "zh" ? q.name_zh : q.name_en)}</span>
        <b>${price(q)}</b>
        ${q.change_pct == null ? "" : `<span class="q-chg ${q.change_pct > 0 ? "up" : q.change_pct < 0 ? "down" : ""}">${q.change_pct > 0 ? "+" : q.change_pct < 0 ? "−" : ""}${Math.abs(q.change_pct).toFixed(2)}%</span>`}
      </div>`).join("")}</div>
    <p class="hint quotes-status">${status}</p>`;
}

// Today's change in each fund's price, next to the holding.
async function loadFundsToday() {
  let data;
  try { data = await api("/api/market/funds"); } catch { return; }
  for (const q of data.quotes || []) {
    const el = panel.querySelector(`[data-today="${CSS.escape(q.id)}"]`);
    if (!el || q.stale || q.change_pct == null) continue;
    el.textContent = ` · ${t("today {v}", { v: `${q.change_pct > 0 ? "+" : q.change_pct < 0 ? "−" : ""}${Math.abs(q.change_pct).toFixed(2)}%` })}`;
    el.classList.add(q.change_pct > 0 ? "up" : q.change_pct < 0 ? "down" : "flat");
  }
}

async function triggerMarket(event, path = `/api/market/event/${event}`) {
  let res;
  try { res = await api(path, { method: "POST" }); }
  catch (err) { note(event === "live_nav" ? t("Today's prices are not available for every part of your plan yet. Please try again later.") : err.message, "msg-error"); return; }
  refreshAudit();
  const c = res.check;
  state.alert = { ...c, decided: null };
  const lines = [
    t("I'm messaging you first because the market moved."),
    t(c.event === "live_nav" ? "{event}: your plan is {change} today, now {amount}." : "{event}: your plan is {change} this month, now {amount}.", { event: eventLabel(c), change: `<strong>${c.change >= 0 ? "+" : "−"}${pct(Math.abs(c.change))}</strong>`, amount: money(c.value_after) }),
  ];
  if (c.loss_limit != null && c.change < 0) {
    lines.push(c.within_limit
      ? t("That is less than the {limit} you said you could lose.", { limit: pct(c.loss_limit, 0) })
      : t("That is more than the {limit} you said you could lose. Let's look at your risk level together before doing anything.", { limit: pct(c.loss_limit, 0) }));
  }
  if (c.rehearsal_sold_at != null && c.change < 0) {
    lines.push(t("In the crash test you sold when it was {sold} down. Today it is {now} down.", { sold: pct(c.rehearsal_sold_at), now: pct(-c.change) }));
  }
  lines.push(adviceLine(c));
  sayAlert(lines);
  if (state.step === "portfolio") { $("#alertSlot").innerHTML = alertCard(state.alert); wireAlert(); $("#alertSlot").scrollIntoView({ behavior: "smooth", block: "start" }); }
  else go("portfolio");
}

function adviceLine(c) {
  if (c.recommendation === "review_risk") return t("My advice: don't sell in a hurry. Let's check your risk level together first.");
  if (c.recommendation === "rebalance") {
    const name = (k) => (LANG === "zh" ? ASSET_NAMES[k] : ASSET_NAMES[k].toLowerCase());
    const sep = LANG === "zh" ? "、" : ", ";
    const sells = c.trades.filter((x) => x.side === "sell").map((x) => name(x.asset_class)).join(sep);
    const buys = c.trades.filter((x) => x.side === "buy").map((x) => name(x.asset_class)).join(sep);
    return t("My advice: bring your plan back to its original split. Sell some {sells} and buy {buys}. Buying what fell helps your plan recover.", { sells, buys });
  }
  return t("My advice: do nothing. Your plan is still close to its original split.");
}

function sayAlert(paragraphs) {
  const li = document.createElement("li");
  li.className = "msg-advisor msg-alert";
  li.innerHTML = `<div class="sig">${t("Keel noticed a market move")}</div>${paragraphs.map((p) => `<p>${p}</p>`).join("")}`;
  thread.append(li);
  thread.scrollTop = thread.scrollHeight;
  notifyChat(li);
}

function alertCard(c) {
  const rows = Object.keys(c.weights_target).map((k) => {
    const d = c.weights_now[k] - c.weights_target[k];
    return `<tr><td><span class="swatch" style="background:var(--${k})"></span>${ASSET_NAMES[k]}</td><td class="r">${pct(c.weights_target[k], 1)}</td><td class="r">${pct(c.weights_now[k], 1)}</td><td class="r ${Math.abs(d) > 0.05 ? "drift-hi" : ""}">${d >= 0 ? "+" : "−"}${pct(Math.abs(d), 1)}</td></tr>`;
  }).join("");
  const decided = c.decided ? `<p class="alert-done">${t("Your decision: {choice}. Recorded in the audit log.", { choice: t(CHOICE_TEXT[c.decided]) })}</p>` : "";
  return `
    <div class="sheet alert-card ${c.change < 0 ? "down" : "up"}">
      <div class="alert-head">
        <div><span class="alert-tag">${t("Market alert")}</span><h3 style="margin:6px 0 0">${esc(eventLabel(c))}</h3></div>
        <div class="alert-move"><b>${c.change >= 0 ? "+" : "−"}${pct(Math.abs(c.change))}</b><span>${t("{after}, was {before}", { after: money(c.value_after), before: money(c.value_before) })}</span></div>
      </div>
      <table><thead><tr><th>${t("Type")}</th><th class="r">${t("Planned")}</th><th class="r">${t("Now")}</th><th class="r">${t("Change")}</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="alert-advice">${adviceLine(c)}</p>
      ${c.decided ? decided : `
      <div class="actions" id="alertActions">
        <button class="btn" type="button" data-choice="${c.recommendation === "rebalance" ? "rebalance" : "hold"}">${t(c.recommendation === "rebalance" ? "Bring back the original split" : "Do nothing")}</button>
        <button class="btn secondary" type="button" data-choice="${c.recommendation === "rebalance" ? "hold" : "rebalance"}">${t(c.recommendation === "rebalance" ? "Do nothing" : "Bring back the original split")}</button>
        <button class="btn secondary sell-btn" type="button" data-choice="sell">${t("Sell everything")}</button>
      </div>
      <div id="alertConfirm"></div>`}
    </div>`;
}

const CHOICE_TEXT = { hold: "do nothing", rebalance: "bring back the original split", sell: "sell everything" };

function wireAlert() {
  panel.querySelectorAll("[data-choice]").forEach((b) => (b.onclick = () => {
    const choice = b.dataset.choice;
    const c = state.alert;
    let warn = "";
    if (choice === "sell") {
      warn = c.rehearsal_sold_at != null
        ? t("In the crash test, selling during the fall left you with {sold} instead of {held}.", { sold: money(state.rehearsal?.final_value_of_choice ?? 0), held: money(state.rehearsal?.final_value_if_held ?? 0) })
        : t("Selling after a fall turns a temporary loss into a real one.");
    }
    const trades = choice === "rebalance" && c.trades.length
      ? `<ul class="reasons">${c.trades.map((x) => `<li>${t(x.side === "sell" ? "Sell {asset}: {amount}" : "Buy {asset}: {amount}", { asset: ASSET_NAMES[x.asset_class], amount: money(x.amount) })}</li>`).join("")}</ul>` : "";
    $("#alertConfirm").innerHTML = `<div class="verdict-bar nudge"><div>${warn ? `<strong>${warn}</strong> ` : ""}${trades}${t("Confirm your decision: {choice}?", { choice: t(CHOICE_TEXT[choice]) })}</div><button class="btn" type="button" id="alertGo">${t("Confirm")}</button></div>`;
    $("#alertGo").onclick = async () => {
      try { await api("/api/market/decision", { method: "POST", body: { event: c.event, choice } }); }
      catch (err) { note(err.message, "msg-error"); return; }
      state.alert = { ...c, decided: choice };
      refreshAudit();
      say([choice === "sell" ? t("Understood. I have saved your decision and my warning. If you like, we can make a safer plan together.") : choice === "rebalance" ? t("Done. Your practice account is back to its original split.") : t("Good decision. Staying invested is how the plan is meant to work. I'll keep watching.")]);
      $("#alertSlot").innerHTML = alertCard(state.alert);
    };
  }));
}

// ---------------------------------------------------------------- 3. crash rehearsal

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const monthName = (ym) => (LANG === "zh" ? `${ym.slice(0, 4)}年${+ym.slice(5)}月` : `${MONTHS[+ym.slice(5) - 1]} ${ym.slice(0, 4)}`);
const REACTION_TEXT = { sell_all: "sell everything", reduce: "sell some", hold: "wait it out", buy_more: "buy more while it is cheap" };

async function renderRehearse() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">${t("Making your plan…")}</p>`;
    try { await loadAllocation(state.client.amount, state.allocationLevel, false); }
    catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  }
  const last = state.rehearsal;
  const reaction = state.answers?.drawdown_reaction;
  panel.innerHTML = `
    <h1>${t("The 2008 crash test")}</h1>
    <p class="lede">${t("Watch your plan go through the 2008 crash and recovery, month by month, with real market data. Press Sell at any moment, or just wait. What you do shows how much risk you really feel comfortable with.")}</p>
    <div class="sheet rehearse-intro">
      <div class="ri-facts">
        <div><span>${t("Your plan")}</span><b>${money(state.allocation.amount)}</b></div>
        <div><span>${t("You said after a 20% fall you would")}</span><b>${esc(REACTION_TEXT[reaction] ? t(REACTION_TEXT[reaction]) : "—")}</b></div>
        <div><span>${t("The most you said you could lose")}</span><b>${state.client?.max_loss ? pct(state.client.max_loss, 0) : "—"}</b></div>
      </div>
      <p class="hint">${t("Takes about 90 seconds. It can only make your plan safer, never riskier.")}</p>
      <div class="actions"><button class="btn" id="startRehearsal" type="button">${last ? t("Try again") : t("Start the test")}</button></div>
    </div>
    <div id="rehearsalResult">${last ? resultCard(last) : ""}</div>
    ${last && !(last.new_class < last.previous_class && state.allocation.investor_class > state.profile.investor_class) ? nextBar("goal", t("Next: check your goal")) : ""}`;
  $("#startRehearsal").onclick = startRehearsal;
  wireResult();
}

async function startRehearsal() {
  let data;
  try { data = await api("/api/rehearsal"); }
  catch (err) { note(err.message, "msg-error"); return; }
  refreshAudit();
  say([
    t("Let's go through it together. This is your plan in the real markets, starting October 2007."),
    t("If you want out at any point, press <strong>Sell everything</strong>. If you do nothing, you keep your investment."),
  ]);
  const pts = data.points;
  const troughIndex = pts.reduce((best, p, i) => (p.drawdown > pts[best].drawdown ? i : best), 0);
  const stage = document.createElement("div");
  stage.className = "theater";
  stage.setAttribute("role", "dialog");
  stage.setAttribute("aria-label", t("2008 crash test"));
  stage.tabIndex = -1;
  let W = 1000, H = 300;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals) * 0.96, hi = Math.max(...vals) * 1.04;
  const X = (i) => (i / (pts.length - 1)) * W;
  const Y = (v) => H - ((v - lo) / (hi - lo)) * H;
  stage.innerHTML = `
    <div class="th-top">
      <div><div class="th-label">${t("2008 crash test")}</div><div class="th-month" id="thMonth">${monthName(pts[0].month)}</div></div>
      <button class="th-quit" id="thQuit" type="button">${t("Stop the test")}</button>
    </div>
    <div class="th-value"><span id="thValue">${money(pts[0].value)}</span><span class="th-change" id="thChange">0.0%</span></div>
    <div class="th-dd" id="thDd">${t("Down from its highest point: {dd}", { dd: "0.0%" })}</div>
    <svg class="th-chart" aria-hidden="true"></svg>
    <div class="th-legend"><span>${t("Flat line: the {amount} you put in", { amount: money(data.amount) })}</span><span>${t("Circles: news")}</span><span id="thLowLabel"></span></div>
    <div class="th-news" aria-live="polite"><span class="th-news-tag">${t("News")}</span><span id="thNews">${t("Markets are calm. Stocks are near record highs.")}</span></div>
    <div class="th-actions">
      <button class="th-sell" id="thSell" type="button"><span>${t("Sell everything")}</span><small id="thSellNote">${t("You have not lost anything yet")}</small></button>
      <button class="th-buy" id="thBuy" type="button"><span>${t("Buy more")}</span><small>${t("Buy more at today's price")}</small></button>
      <span class="th-hint" id="thHint">${t("Do nothing to keep your investment.")}</span>
    </div>`;
  document.body.append(stage);
  // Draw in real pixels so the marker stays round and lines keep their weight at any size.
  const chart = $(".th-chart", stage);
  ({ width: W, height: H } = chart.getBoundingClientRect());
  chart.setAttribute("viewBox", `0 0 ${W} ${H}`);
  chart.innerHTML = `
      <defs>
        <clipPath id="thBelow"><rect x="0" y="${Y(data.amount)}" width="${W}" height="${H}"/></clipPath>
        <clipPath id="thAbove"><rect x="0" y="0" width="${W}" height="${Y(data.amount)}"/></clipPath>
      </defs>
      <path class="th-area" id="thArea" d="" clip-path="url(#thBelow)"/>
      <path class="th-area up" id="thAreaUp" d="" clip-path="url(#thAbove)"/>
      <line class="th-base" x1="0" x2="${W}" y1="${Y(data.amount)}" y2="${Y(data.amount)}"/>
      <line class="th-low" id="thLow" x1="0" x2="${W}" y1="-10" y2="-10"/>
      <path class="th-line" id="thLine" d=""/>
      <g id="thTicks"></g>
      <circle class="th-dot" id="thDot" r="5" cx="0" cy="${Y(pts[0].value)}"/>
`;
  stage.focus();

  // ?demo plays the same months about three times faster, for recorded demos.
  const fast = new URLSearchParams(location.search).has("demo");
  const pace = { start: fast ? 600 : 1200, crash: fast ? 650 : 1500, recovery: fast ? 110 : 330 };
  let i = 0, done = false, boughtAt = null, timer = null, low = pts[0].value;
  const tick = () => {
    if (done) return;
    i += 1;
    const p = pts[i];
    const line = pts.slice(0, i + 1).map((q, k) => `${k ? "L" : "M"}${X(k).toFixed(1)},${Y(q.value).toFixed(1)}`).join("");
    $("#thLine").setAttribute("d", line);
    const base = Y(data.amount).toFixed(1);
    const area = `${line}L${X(i).toFixed(1)},${base}L0,${base}Z`;
    $("#thArea").setAttribute("d", area);
    $("#thAreaUp").setAttribute("d", area);
    if (p.value < low) {
      low = p.value;
      $("#thLow").setAttribute("y1", Y(low)); $("#thLow").setAttribute("y2", Y(low));
      $("#thLowLabel").textContent = t("Dashed line: lowest so far, {v}", { v: money(low) });
    }
    if (p.headline) $("#thTicks").insertAdjacentHTML("beforeend", `<circle class="th-tick" r="3.5" cx="${X(i)}" cy="${Y(p.value)}"/>`);
    $("#thDot").setAttribute("cx", X(i)); $("#thDot").setAttribute("cy", Y(p.value));
    const change = p.value / data.amount - 1;
    $("#thMonth").textContent = monthName(p.month);
    $("#thValue").textContent = money(p.value);
    $("#thChange").textContent = `${change >= 0 ? "+" : "−"}${pct(Math.abs(change))}`;
    $("#thDd").textContent = t("Down from its highest point: {dd}", { dd: `−${pct(p.drawdown)}` });
    stage.classList.toggle("red", change < 0);
    $("#thSellNote").textContent = change < 0
      ? t("You would lose {v} for good", { v: money(data.amount - p.value) })
      : t("You would keep a gain of {v}", { v: money(p.value - data.amount) });
    if (p.headline) { const n = $("#thNews"); n.textContent = t(p.headline); n.classList.remove("flash"); void n.offsetWidth; n.classList.add("flash"); }
    if (i === troughIndex) $("#thHint").textContent = t("This is the moment most investors sell.");
    if (i === troughIndex + 3) $("#thHint").textContent = t("Do nothing to keep your investment.");
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
  $("#thBuy").onclick = (e) => { if (boughtAt === null) { boughtAt = i; const b = e.currentTarget; b.firstElementChild.textContent = t("Bought more"); b.disabled = true; } };
  $("#thQuit").onclick = () => { done = true; clearTimeout(timer); stage.remove(); note(t("Test stopped. Nothing about your risk level was changed.")); };
  stage.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#thQuit").click(); });
  timer = setTimeout(tick, pace.start);
}

function resultCard(o) {
  const sold = o.action === "sell";
  const lowered = o.new_class < o.previous_class;
  const gap = o.final_value_if_held - o.final_value_of_choice;
  return `
    <h3>${t("Your result")}</h3>
    <div class="sheet rehearse-result ${sold ? "sold" : "held"}">
      <p class="rr-head">${sold
        ? t("You sold in {month}, when it was {dd} down.", { month: monthName(o.month), dd: pct(o.drawdown_at_decision) })
        : t("You stayed in through the worst of it: {dd} down in {month}.", { dd: pct(o.max_drawdown), month: monthName(o.trough_month) })}</p>
      <div class="rr-compare">
        <div><span>${t("If you had waited until March 2013")}</span><b>${money(o.final_value_if_held)}</b></div>
        <div><span>${t(sold ? "What you had after selling" : o.action === "buy_more" ? "You waited and even bought more" : "What you ended with")}</span><b>${money(o.final_value_of_choice)}</b></div>
        ${sold ? `<div class="rr-gap"><span>${t("Selling cost you")}</span><b>−${money(gap)}</b></div>` : ""}
      </div>
      <p>${lowered
        ? t("Your answers said <strong>{a}</strong>, but what you did fits <strong>{b}</strong> better. We lowered your risk level: a plan you can stick with is better than one you give up on at the bottom.", { a: esc(LEVEL[o.previous_class]), b: esc(LEVEL[o.new_class]) })
        : sold
          ? t("Your level already allows a loss that size, so it stays <strong>{level}</strong>.", { level: esc(LEVEL[o.new_class]) })
          : t("What you did fits your risk level, <strong>{level}</strong>.", { level: esc(LEVEL[o.new_class]) })}</p>
      ${lowered ? `<div class="actions"><button class="btn" type="button" id="rebuildAtNew">${t("Update my plan to {level}", { level: esc(LEVEL[o.new_class]) })}</button></div>` : ""}
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
      t("You sold in {month}, when it was {dd} down. Waiting would have left you <strong>{held}</strong> by March 2013. Selling left {sold}.", { month: monthName(o.month), dd: pct(o.drawdown_at_decision), held: money(o.final_value_if_held), sold: money(o.final_value_of_choice) }),
      lowered
        ? t("That tells me more than the questions did. I lowered your risk level to <strong>{level}</strong> so the plan fits how you really react.", { level: esc(LEVEL[o.new_class]) })
        : t("Your level already allows a loss that size, so it stays the same."),
    ]);
  } else {
    say([
      t("You stayed in through a {dd} fall. By March 2013 your plan was worth <strong>{v}</strong>.", { dd: pct(o.max_drawdown), v: money(o.final_value_if_held) }),
      t("What you did fits the risk level from your answers."),
    ]);
  }
}

// ---------------------------------------------------------------- 4. goal

const short = (v) => (v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : `${Math.round(v)}`);
const GOAL_KINDS = ["Buy a home", "Children's education", "Retirement", "Something else"];  // keys; labels via t()

async function renderGoal() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">${t("Making your plan…")}</p>`;
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
    <p class="lede">${t("We play out 5,000 possible futures for your {amount} and count how many reach your goal.", { amount: money(state.allocation.amount) })}</p>
    <div class="sheet">
      <div class="filters" role="radiogroup" aria-label="${t("Goal")}">
        ${(GOAL_KINDS.includes(g.name) ? GOAL_KINDS : [g.name, ...GOAL_KINDS]).map((k) => `<label class="chip"><input type="radio" name="gk" value="${esc(k)}" ${k === g.name ? "checked" : ""}><span>${esc(t(k))}</span></label>`).join("")}
      </div>
      <div class="facts">
        <div class="field"><label for="gTarget">${t("Goal amount")}</label><input id="gTarget" type="number" min="1000" step="1000" value="${g.target}"></div>
        <div class="field"><label for="gYears">${t("In")} <span class="range-value" id="gYearsV">${t("{n} yrs", { n: g.years })}</span></label><input id="gYears" type="range" min="1" max="40" value="${g.years}"></div>
        <div class="field"><label for="gMonthly">${t("You add each month")}</label><input id="gMonthly" type="number" min="0" step="100" value="${g.monthly}"></div>
        <label class="check"><input id="gInfl" type="checkbox" ${g.inflation ? "checked" : ""}> ${t("Allow for prices rising 2% a year")}</label>
      </div>
    </div>
    <div id="goalOut"><p class="empty" style="margin-top:20px">${t("Simulating…")}</p></div>
    ${nextBar("execute", t("Next: invest"))}`;
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
        <div class="goal-line">${t("chance of having <b>{amount}</b> by {year}", { amount: money(r.target_nominal), year })}</div>
        ${input.inflation ? `<div class="goal-sub">${t("That is {amount} in today's money, with prices rising 2% a year.", { amount: money(input.target) })}</div>` : ""}
      </div>
    </div>
    ${r.required_monthly === null ? "" : r.required_monthly <= input.monthly
      ? `<div class="verdict-bar ok"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg><div>${t("<strong>You are on track.</strong> What you add each month is enough for at least an 8 in 10 chance.")}</div></div>`
      : `<div class="verdict-bar nudge"><div>${t("Add <strong>{amount}</strong> a month for an 8 in 10 chance.", { amount: num(money(r.required_monthly), prov, t("Monthly amount needed for an 8 in 10 chance")) })}</div><button class="btn secondary" type="button" id="useMonthly">${t("Use {amount} a month", { amount: money(r.required_monthly) })}</button></div>`}
    <div class="sheet" style="margin-top:16px">
      ${fanChart(r.fan, r.target_nominal)}
      <div class="legend fan-legend">
        <span><i class="line-median"></i>${t("Most likely")}</span>
        <span><i class="band-inner"></i>${t("Half of futures")}</span>
        <span><i class="band-outer"></i>${t("8 in 10 futures")}</span>
        <span><i class="line-target"></i>${t("Your goal")}</span>
      </div>
    </div>
    <div class="kpis" style="margin-top:16px;grid-template-columns:repeat(3,1fr)">
      <div class="kpi"><div class="k">${t("If markets go badly")}</div><span class="v">${num(money(r.terminal_p10), prov, t("1 future in 10 ends lower than this"))}</span></div>
      <div class="kpi"><div class="k">${t("Most likely")}</div><span class="v">${num(money(r.terminal_p50), prov, t("Half of futures end above this, half below"))}</span></div>
      <div class="kpi"><div class="k">${t("If markets go well")}</div><span class="v">${num(money(r.terminal_p90), prov, t("1 future in 10 ends higher than this"))}</span></div>
    </div>
    <details class="assume"><summary>${t("How we calculate this")}</summary><ul>
      <li>${t("We use the expected growth ({ret} a year after fees) and normal ups and downs (±{vol}) of your plan.", { ret: pct(state.allocation.expected_return), vol: pct(state.allocation.volatility) })}</li>
      <li>${t("Each future moves month by month. The same numbers always give the same answer.")}</li>
      <li>${t("Real markets can crash harder than this model expects. Taxes are not included.")}</li>
    </ul></details>`;
  const use = $("#useMonthly");
  if (use) use.onclick = () => { $("#gMonthly").value = r.required_monthly; runGoal({ ...input, monthly: r.required_monthly }); };
  wireFan(r.fan, r.target_nominal);
  state.done.add("goal");
  if (!state.goalNarrated) {
    state.goalNarrated = true;
    say([
      t("Adding {amount} a month, about <strong>{n} in 100</strong> futures reach {target} by {year}.", { amount: money(input.monthly), n: chance, target: money(r.target_nominal), year }),
      r.required_monthly && r.required_monthly > input.monthly
        ? t("Adding {amount} a month would make it <strong>80 in 100</strong>. Waiting longer also helps. Taking more risk than your level allows is not something I can offer.", { amount: money(r.required_monthly) })
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
      <text class="target-label" x="${L + 8}" y="${y(target) - 7}" text-anchor="start">${t("Goal {v}", { v: short(target) })}</text>
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
    tip.innerHTML = `<b>${i === 0 ? t("Today") : t("Year {n}", { n: i })}</b><div>${t("Most likely {v}", { v: money(f.p50) })}</div><div class="dim">${t("8 in 10 between {a} and {b}", { a: short(f.p10), b: short(f.p90) })}</div>`;
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

const KIND_NAMES = { deposit: "Bank deposit", large_cd: "Large bank deposit", savings_bond: "Government savings bond" };
const KIND_ICON = {
  bank: '<svg viewBox="0 0 24 24" class="kind-icon"><path d="M3 9l9-5 9 5M5 10v8M10 10v8M14 10v8M19 10v8M3 20h18"/></svg>',
  bond: '<svg viewBox="0 0 24 24" class="kind-icon"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg>',
};

// Three things to compare: funds (filtered by type), bank deposits, and government savings bonds.
const COMPARE_TABS = { funds: "Funds", deposits: "Bank deposits", bonds: "Savings bonds" };
const termText = (m) => (m % 12 ? tn("1 month", "{n} months", m) : tn("1 year", "{n} years", m / 12));

async function renderCompare(tab = "funds", asset = "") {
  panel.innerHTML = `<p class="empty">${t("Loading…")}</p>`;
  const query = tab === "deposits" ? ["deposit", "large_cd"] : tab === "bonds" ? ["savings_bond"] : [asset];
  let data;
  try {
    const parts = await Promise.all(query.map((q) => api(`/api/compare${q ? `?asset_class=${q}` : ""}`)));
    data = { ...parts[0], rows: parts.flatMap((x) => x.rows) };
  } catch (err) { panel.innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
  if (tab === "funds") data.rows = data.rows.filter((r) => (r.kind || "fund") === "fund");
  else {
    // Banks with the same offer share one row: "ABC, BOC, CCB ...  1 year  0.95%".
    const groups = new Map();
    for (const r of data.rows) {
      const key = [r.kind, r.term_months, r.rate, r.promo, r.insured, r.early_withdrawal_cost_6m].join("|");
      if (groups.has(key)) groups.get(key).issuers.push(r.issuer || r.name);
      else groups.set(key, { ...r, issuers: [r.issuer || r.name] });
    }
    data.rows = [...groups.values()].map((r) => ({ ...r, issuer: r.issuers.join(LANG === "zh" ? "、" : ", ") }));
    data.rows.sort((a, b) => b.rate - a.rate || b.term_months - a.term_months);
  }
  state.done.add("compare");
  refreshAudit();
  const prov = data.provenance;
  const c = state.client;
  const tabs = `<div class="tabs" role="tablist">${Object.entries(COMPARE_TABS).map(([k, label]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}">${t(label)}</button>`).join("")}</div>`;
  const lede = {
    funds: t("All funds that fit your risk level, best value first. \"Fees over {years} years\" is what fees would cost on {amount}.", { amount: money(c.amount), years: c.horizon_years }),
    deposits: t("Fixed interest, no ups and downs. The state insures up to 500,000 per person in each bank. If you take money out early, you only get 0.05% a year on it."),
    bonds: t("Issued by China's Ministry of Finance, fixed interest, no ups and downs. On sale until {date}, at most 500,000 per person. Taking money out in the first 6 months earns no interest.", { date: longDate(data.rows[0]?.sale_to || "2026-10-19") }),
  }[tab];
  const fundTable = `
      <table>
        <thead><tr><th>${t("Fund")}</th><th>${t("Risk")}</th><th class="r">${t("May grow a year")}</th><th class="r">${t("Ups and downs")}</th><th class="r">${t("Fee a year")}</th><th class="r">${t("Fees over {years} years", { years: c.horizon_years })}</th><th class="r">${t("Get money back in")}</th></tr></thead>
        <tbody>
          ${data.rows.map((r) => `
            <tr>
              <td class="prod"><span class="swatch" style="background:var(--${r.asset_class})"></span>${r.source ? `<a class="fund-link" href="${esc(r.source)}" target="_blank" rel="noopener">${esc(r.name)}</a>` : esc(r.name)}<small>${ASSET_NAMES[r.asset_class]}</small></td>
              <td><span class="risk">${RISK[r.risk_class]}</span></td>
              <td class="r">${num(pct(r.net_return, 1), prov, t("Expected growth a year after fees: {name}", { name: r.name }))}</td>
              <td class="r">±${pct(r.volatility, 1)}</td>
              <td class="r">${pct(r.fee, 2)}</td>
              <td class="r">${num(money(r.fee_drag), prov, t("Fees over {years} years: {name}", { years: c.horizon_years, name: r.name }))}</td>
              <td class="r">${r.liquidity_days <= 31 ? tn("1 day", "{n} days", r.liquidity_days) : t("{n} months", { n: Math.round(r.liquidity_days / 30) })}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  const fixedTable = `
      <table>
        <thead><tr><th>${t(tab === "bonds" ? "Bond" : "Bank")}</th><th>${t("For")}</th><th class="r">${t("Interest a year")}</th><th class="r">${t("Cost of taking {amount} out after 6 months", { amount: money(c.amount) })}</th><th>${t("Protection")}</th></tr></thead>
        <tbody>
          ${data.rows.map((r) => `
            <tr>
              <td class="prod">${esc(r.issuer || r.name)}${r.kind === "large_cd" ? `<small>${t("Large deposit, from 200,000")}</small>` : r.promo ? `<small>${t("Special offer, new money only")}</small>` : ""}</td>
              <td>${termText(r.term_months)}</td>
              <td class="r"><b>${num(pct(r.rate, 2), prov, t("Interest a year: {name}", { name: r.name }))}</b></td>
              <td class="r">${r.early_withdrawal_cost_6m == null ? "—" : num(money(r.early_withdrawal_cost_6m), prov, t("Interest lost by taking the money out after 6 months: {name}", { name: r.name }))}</td>
              <td>${r.kind === "savings_bond" ? t("Backed by the state") : r.insured ? t("Insured") : t("Insured up to 500,000")}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  panel.innerHTML = `
    <h1>${t("Compare")}</h1>
    ${tabs}
    <p class="lede">${lede}</p>
    ${tab === "funds" ? `${dataNote()}<div class="filters">
      ${["", ...ASSET_ORDER].map((k) => `<label class="chip"><input type="radio" name="af" value="${k}" ${k === asset ? "checked" : ""}><span>${k ? ASSET_NAMES[k] : t("All")}</span></label>`).join("")}
    </div>` : `<p class="data-note">${t("Rates published by the banks and the Ministry of Finance, as of {date}. Banks can change them.", { date: longDate("2026-10-12") })}</p>`}
    <div class="sheet">
      ${data.rows.length ? (tab === "funds" ? fundTable : fixedTable) : `<p class="empty">${t(tab === "funds" ? "No funds of this type fit your risk level." : tab === "bonds" ? "The savings bonds on sale now last 3 or 5 years. That is longer than you plan to invest ({n} years)." : "No deposit is short enough for when you need the money.", { n: c.horizon_years })}</p>`}
    </div>
    ${tab === "funds" && data.locked?.length ? `<details class="assume hidden-note"><summary>${tn("1 fund hidden: you may need your money sooner than it allows", "{n} funds hidden: you may need your money sooner than they allow", data.locked.length)}</summary><ul>${data.locked.map((h) => `<li>${esc(h.name)}</li>`).join("")}</ul></details>` : ""}
    ${tab === "funds" && data.hidden.length ? `<details class="assume hidden-note"><summary>${tn("1 fund hidden: riskier than your level", "{n} funds hidden: riskier than your level", data.hidden.length)}</summary><ul>${data.hidden.map((h) => `<li>${esc(h.name)}, ${RISK[h.risk_class].toLowerCase()}</li>`).join("")}</ul></details>` : ""}
    ${nextBar(null, "", { back: true })}`;
  panel.querySelectorAll('input[name="af"]').forEach((i) => (i.onchange = () => renderCompare("funds", i.value)));
  panel.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => renderCompare(b.dataset.tab)));
}

// ---------------------------------------------------------------- 6. stress

async function renderStress() {
  if (!state.allocation) { await renderPortfolio(); }
  panel.innerHTML = `<p class="empty">${t("Replaying the crises…")}</p>`;
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
    <h1>${t("How would your plan do in a crisis?")}</h1>
    <p class="lede">${t("We replay three real crises on your {amount} and compare the loss with the {limit} you said you could lose. Real losses can be bigger.", { amount: money(state.allocation.amount), limit: pct(data.max_loss, 0) })}</p>
    <div class="sheet" style="padding-top:40px">
      ${data.scenarios.map((s, i) => `
        <div class="stress-row">
          <div class="name">${esc(LANG === "zh" ? t(s.name) : s.name[0].toUpperCase() + s.name.slice(1))}</div>
          <div class="stress-track">
            <div class="stress-bar ${s.breach ? "breach" : ""}" style="width:${x(s.loss)}"></div>
            <div class="stress-val" style="left:${x(s.loss)}">${s.loss < 0.0005 ? t("No loss") : `−${pct(s.loss)} <span style="font-weight:400;color:var(--ink-3)">(${num(money(s.loss_amount), prov, t("Loss in {name}", { name: t(s.name) }))})</span>`}</div>
            <div class="limit" style="left:${x(data.max_loss)}"></div>
            ${i === 0 ? `<div class="limit-label" style="left:${x(data.max_loss)}">${t("Your limit {v}", { v: pct(data.max_loss, 0) })}</div>` : ""}
          </div>
        </div>`).join("")}
      <div class="verdict-bar ${breaches.length ? "bad" : "ok"}">
        ${breaches.length
          ? `<svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg><div>${t("<strong>More than your limit in {n} of {total} crises.</strong> Think about choosing less risk in your plan.", { n: breaches.length, total: data.scenarios.length })}</div>`
          : `<svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg><div>${t("<strong>Within your limit in every crisis.</strong> The worst case is a {v} fall.", { v: pct(Math.max(...data.scenarios.map((s) => s.loss))) })}</div>`}
      </div>
    </div>
    ${nextBar(null, "", { back: true })}`;
  const worst = data.scenarios.reduce((a, b) => (b.loss > a.loss ? b : a));
  say([
    t("If the {name} happened again, your plan would fall about <strong>{v}</strong>, or {amount}.", { name: esc(t(worst.name)), v: pct(worst.loss), amount: money(worst.loss_amount) }),
    breaches.length
      ? t("That is more than the {limit} you told me you could lose, so I would not go ahead at this risk level.", { limit: pct(data.max_loss, 0) })
      : t("That is within the {limit} you told me you could lose.", { limit: pct(data.max_loss, 0) }),
  ]);
}

// ---------------------------------------------------------------- 7. execute

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const shortDate = (iso) => new Date(iso).toLocaleDateString(LOCALE, { day: "numeric", month: "short" });

function setTier(tier) {
  state.tier = tier;
  const el = $(".tier");
  el.textContent = tier.level >= 3 ? t("Practice buying on") : t("Advice only");
  el.classList.toggle("live", tier.level >= 3);
  el.title = tier.level >= 3
    ? t("You signed the risk notice. Every order still needs you to press and hold the button.")
    : t("The advisor can explain and suggest, but cannot buy or sell anything.");
}

async function renderExecute() {
  if (!state.allocation) {
    panel.innerHTML = `<p class="empty">${t("Making your plan…")}</p>`;
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
    <h1>${t("Before you invest")}</h1>
    <p class="lede">${t("This is a practice account with play money. Read these points and sign. You will still confirm every order yourself.")}</p>
    <div class="sheet disclosure">
      <h3 style="margin-top:0">${t("Please read")}</h3>
      <ul class="reasons">
        <li>${t("Investments can go down. You may get back less than you put in.")}</li>
        <li>${t("Our numbers are estimates based on the past. The future can be different.")}</li>
        <li>${t("Your risk level is {level}. Riskier funds are blocked for you.", { level: esc(LEVEL[p.investor_class]) })}</li>
        <li>${t("Medium to high and high risk funds wait 24 hours before they are bought. You can cancel during the wait.")}</li>
        <li>${t("The AI advisor can never buy or sell for you.")}</li>
      </ul>
      ${tier.kill_switch ? `<div class="verdict-bar bad"><div>${t("<strong>Buying is switched off for everyone right now.</strong> You can still use every advice step.")}</div></div>` : `
      <form id="consent" class="sign">
        <label class="check" style="padding-top:18px"><input type="checkbox" id="accept"> ${t("I have read and understood these points")}</label>
        <div class="field sign-field">
          <label for="signName">${t("Type your full name to sign")}</label>
          <input id="signName" type="text" autocomplete="name" placeholder="${t("Your full name")}" maxlength="80">
          <div class="signature" aria-hidden="true"><span id="sigInk"></span></div>
        </div>
        <div class="actions"><button class="btn" id="signBtn" type="submit" disabled>${t("Sign and continue")}</button></div>
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
      say([t("Thank you. You can now place practice orders."), t("I have prepared your orders from your plan. Nothing is bought until you press and hold the button yourself.")]);
      renderTicket();
    } catch (err) {
      $("#consentErr").innerHTML = `<p class="err">${esc(err.message)}</p>`;
      $("#signBtn").disabled = false;
    }
  };
}

async function renderTicket() {
  if (staleBanner()) {
    panel.innerHTML = `<h1>${t("Check and confirm")}</h1><p class="lede">${t("Your risk level changed after this plan was made.")}</p>${staleBanner()}`;
    wireStale();
    return;
  }
  panel.innerHTML = `<p class="empty">${t("Preparing your orders…")}</p>`;
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
    <h1>${t("Check and confirm")}</h1>
    <p class="lede">${t("These orders match your plan exactly. Our system checked each one against your risk level and limits.")}</p>
    ${state.rehearsal ? "" : `<div class="verdict-bar nudge"><div>${t("<strong>You haven't tried the 2008 crash test yet.</strong> Most people who sell in a crash never expected to.")}</div><button class="btn secondary" type="button" id="goRehearse">${t("Try it first")}</button></div>`}
    <div class="exec">
      <div class="ticket">
        <div class="ticket-head">
          <div><div class="ticket-sub">${t("Your orders")}</div><div class="ticket-title">${later.length ? t("{a} now, {b} after a 24-hour wait", { a: tn("1 fund", "{n} funds", now.length), b: later.length }) : tn("1 fund", "{n} funds", now.length)}</div></div>
          <div class="ticket-acct"><div class="ticket-sub">${t("Practice money")}</div><b>${num(money(d.cash), d.provenance, t("Money in your practice account"))}</b></div>
        </div>
        <div class="perf" aria-hidden="true"></div>
        <ul class="ticket-lines">
          ${[...now, ...later].map((o) => `
            <li class="${o.cooling_off ? "muted" : ""}">
              <span class="swatch" style="background:var(--${o.asset_class})"></span>
              <span class="tl-name">${esc(o.name)}<small>${RISK[o.risk_class]}${o.cooling_off ? `, ${t("bought on {date}", { date: shortDate(o.cooling_off_until) })}` : ""}</small></span>
              <span class="tl-amt">${money(o.amount)}</span>
            </li>`).join("")}
        </ul>
        ${later.length ? `<p class="hint cooling-note">${t("Riskier funds wait 24 hours before they are bought, so you never buy them in a rush. You can cancel during the wait.")}</p>` : ""}
        <div class="perf" aria-hidden="true"></div>
        <ul class="checks">
          <li>${t("Every fund fits your risk level")}</li>
          <li class="${state.rehearsal ? "" : "todo"}">${state.rehearsal ? t("2008 crash test done") : t("2008 crash test not done yet")}</li>
          <li>${t("Within your order limits")}</li>
          <li>${t("Your answers are valid until {date}", { date: longDate(state.profile.expires_on) })}</li>
        </ul>
        <div class="ticket-total"><span>${t(later.length ? "You pay now" : "Total")}</span><b>${money(total)}</b></div>
      </div>

      <div class="confirm-zone">
        ${now.length ? `
        <button class="hold" id="hold" type="button" aria-describedby="holdHint">
          <span class="hold-label">${t("Press and hold to buy")}</span>
          <span class="hold-fill" aria-hidden="true">${t("Press and hold to buy")}</span>
        </button>
        <p class="hint" id="holdHint">${t("Hold for 1.5 seconds. You can undo for 5 seconds after.")}</p>` : `<p class="empty">${t("All orders are waiting 24 hours.")}</p>`}
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
    undo.innerHTML = `<span>${t('Buying in <b id="undoN">{n}</b> s', { n: left })}</span><button type="button" class="btn secondary" id="undoBtn">${t("Undo")}</button>`;
    btn.hidden = true;
    $("#holdHint").hidden = true;
    zone.prepend(undo);
    $("#undoBtn").focus();
    const timer = setInterval(async () => {
      left -= 1;
      if (left > 0) { $("#undoN").textContent = left; return; }
      clearInterval(timer);
      undo.innerHTML = `<span>${t("Buying…")}</span>`;
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
      note(t("Cancelled. Nothing was bought."));
      btn.focus();
    };
  }
  function reset() { done = false; btn.classList.remove("armed"); set(0); }
}

function printReceipt(r) {
  const printer = $("#printer");
  const paper = $("#paper");
  const ts = new Date(r.provenance.timestamp);
  const later = (state.drafts?.orders || []).filter((o) => o.cooling_off);
  const settle = r.executed[0]?.settles_on;
  const line = (l, rgt) => `<div class="rl"><span>${l}</span><span>${rgt}</span></div>`;
  const hash = r.provenance.audit_hash;
  paper.innerHTML = `
    <div class="rl"><span class="rc-head">${t("Purchase receipt")}</span><span class="rc-dim">${ts.toLocaleDateString(LOCALE, { day: "2-digit", month: "short", year: "numeric" })} ${ts.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" })}</span></div>
    <div class="rc-dim">${t("Practice account")}</div>
    <div class="rc-rule"></div>
    <table class="rc-table">
      <thead><tr><th>${t("Fund")}</th><th class="r">${t("Units")}</th><th class="r">${t("Price per unit")}</th><th class="r">${t("Amount")}</th></tr></thead>
      <tbody>
        ${r.executed.map((o) => `<tr><td>${esc(o.name)}<small>${t("Bought")}</small></td><td class="r">${o.units.toFixed(2)}</td><td class="r">${o.nav.toFixed(4)}</td><td class="r">${money(o.amount)}</td></tr>`).join("")}
        ${later.map((o) => `<tr class="rc-dim"><td>${esc(o.name)}<small>${t("bought on {date}", { date: shortDate(o.cooling_off_until) })}</small></td><td class="r">–</td><td class="r">–</td><td class="r">${money(o.amount)}</td></tr>`).join("")}
        ${r.failed.map((f) => `<tr class="rc-fail"><td colspan="4">${t("Not placed: {why}", { why: esc(f.reason) })}</td></tr>`).join("")}
      </tbody>
    </table>
    <div class="rc-rule"></div>
    ${line(`<b>${t("Total executed")}</b>`, `<b>${money(r.total)}</b>`)}
    ${line(t("Practice money left"), money(r.cash))}
    ${settle ? line(t("Funds arrive"), shortDate(settle)) : ""}
    ${line(t("Risk check"), t("Every fund fits your level"))}
    <div class="rc-rule"></div>
    ${line(t("Record number"), `<span class="rc-hash" title="${esc(hash)}">${hash.slice(0, 10)}…${hash.slice(-6)}</span>`)}`;
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
      ? tn("Done. You bought 1 fund for <strong>{amount}</strong> in your practice account. It arrives in two working days.", "Done. You bought {n} funds for <strong>{amount}</strong> in your practice account. They arrive in two working days.", r.executed.length, { amount: money(r.total) })
      : t("Nothing was bought."),
    ...(later.length ? [tn("1 riskier fund will be bought after the 24-hour wait.", "{n} riskier funds will be bought after the 24-hour wait.", later.length)] : []),
    t("Your receipt has a record number, so this purchase can be checked later."),
  ]);
}

async function anchorOnReceipt(paper) {
  const slot = document.createElement("div");
  slot.className = "rc-chain";
  slot.innerHTML = `<div class="rc-rule"></div><div class="rc-dim">${t("Saved on a blockchain")}</div><div>${t("Saving on {net}…", { net: chainName() })}</div>`;
  paper.append(slot);
  try {
    const a = await api("/api/anchor", { method: "POST" });
    const txText = `${esc(a.tx_hash?.slice(0, 10) || "")}…${esc(a.tx_hash?.slice(-6) || "")}`;
    slot.lastElementChild.innerHTML = a.sent
      ? `${esc(chainName(a.network, true))}${a.block ? `, ${t("block {n}", { n: a.block })}` : ""}<br>${a.explorer_url ? `<a href="${esc(a.explorer_url)}" target="_blank" rel="noopener">${txText}</a>` : txText}`
      : `<span class="rc-dim">${t("Not saved: {why}", { why: esc(a.note) })}</span>`;
    refreshAudit();
  } catch (err) {
    slot.lastElementChild.innerHTML = `<span class="rc-dim">${t("Not saved: {why}", { why: esc(err.message) })}</span>`;
  }
}

// ---------------------------------------------------------------- audit drawer

// Plain names for audit events; unknown events fall back to their code.
const EVENT_NAMES = {
  advisory_flow: "Advice step", confirmation_token_issued: "You confirmed an order", draft_orders_created: "Orders prepared",
  guard_blocked: "Unsafe message blocked", input_guard: "Message checked for safety", llm_call: "AI advisor replied",
  llm_error: "AI service error", llm_key_cooldown: "AI service busy, switched", llm_provider_skipped: "AI service skipped",
  llm_retry_wait: "AI service retry", market_refresh: "Market prices updated", market_quotes: "Market prices shown",
  market_quotes_viewed: "Market prices shown", order_executed: "Fund bought", order_rejected: "Order refused",
  prompt_guard_call: "Message checked for tricks", prompt_guard_error: "Safety check error", session_turn: "Chat message",
  tool_call: "Calculation done", tool_error: "Calculation error", tool_output_blocked: "Unsafe data blocked",
  advice_report_issued: "Report created", audit_anchored: "Saved on blockchain", rehearsal_decision: "Crash test result",
  rehearsal_started: "Crash test started", risk_disclosure_signed: "Risk notice signed", consent_signed: "Recommendation accepted", ui_allocation_built: "Plan made",
  ui_goal_projected: "Goal checked", ui_orders_confirmed: "Orders confirmed", ui_orders_drafted: "Orders prepared",
  ui_products_compared: "Funds compared", ui_profile_assessed: "Risk level worked out", ui_stress_tested: "Crises replayed",
  market_event: "Market alert", market_decision: "Your decision on a market alert",
};

const drawer = $("#drawer");
const scrim = $("#scrim");
let lastFocus = null;
async function refreshAudit() {
  try {
    const a = await api("/api/audit");
    const pill = $("#auditPill");
    pill.classList.toggle("ok", a.valid);
    pill.classList.toggle("bad", !a.valid);
    $("#auditText").textContent = a.valid ? t("Activity log") : t("Log was changed!");
    pill.title = a.valid ? t("{n} records, all checked", { n: a.total }) : "";
    return a;
  } catch { return null; }
}
async function openDrawer() {
  lastFocus = document.activeElement;
  const a = await refreshAudit();
  if (!a) return;
  $("#drawerStatus").textContent = a.valid
    ? t("Every step is saved here: {n} records. Each record is linked to the one before, so no one can change the past without it showing.", { n: a.total })
    : t("Check failed: {why}", { why: a.reason });
  renderAnchors();
  $("#chain").innerHTML = a.records.map((r) => `
    <li title="${esc(r.source || "")}">
      <div class="ev">${esc(EVENT_NAMES[r.event] ? t(EVENT_NAMES[r.event]) : r.event.replace(/_/g, " "))}</div>
      <div class="src">${esc(new Date(r.timestamp).toLocaleString(LOCALE))}</div>
      <div class="h">${esc(r.hash.slice(0, 16))}…</div>
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
      <div><b>${t("Copies on a blockchain")}</b><div class="hint">${sent.length ? t("{n} on {net}", { n: sent.length, net: chainName(sent[0].network) }) : t("Save a fingerprint of this log on {net}.", { net: chainName() })}</div></div>
      <button class="btn secondary" type="button" id="anchorNow">${t("Save now")}</button>
    </div>
    ${sent.slice().reverse().map((x) => `
      <div class="anchor-row">
        ${x.explorer_url ? `<a href="${esc(x.explorer_url)}" target="_blank" rel="noopener">${esc(x.tx_hash.slice(0, 12))}…</a>` : `<code>${esc(x.tx_hash.slice(0, 12))}…</code>`}
        <span class="rc-dim">${x.block ? `${t("block {n}", { n: x.block })}, ` : ""}${t("{n} records", { n: x.record_count })}</span>
        <button class="why" type="button" data-verify="${esc(x.tx_hash)}">${t("Check")}</button>
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
      out.textContent = v.matches ? t("Matches the log at record {n}, block {b}.", { n: v.record_count, b: v.block }) : t("Does not match: {why}", { why: v.chain_reason });
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
    t("Hello! I'm your investment advisor."),
    t("First, 8 short questions so I know how much risk is right for you. It takes about two minutes."),
    t("You can ask me anything here at any time."),
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
    if (restored.profile) note(t("Welcome back. Your answers and plan are restored."));
  } catch { /* a fresh session simply starts at step 1 */ }
  go(state.profile ? (state.allocation ? "portfolio" : "profile") : "profile");
  refreshAudit();
})();
