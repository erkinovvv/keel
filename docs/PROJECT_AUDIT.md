# Keel project audit — Topic B Wealth Advisory Agent

**Audit date:** 15 October 2026 (UTC+8)
**Repository revision:** `9264797` (`Parallelize live market providers and fix money market NAVs`)
**Scope:** source code, tests, evidence pack, product documentation, deployment files, competition brief, and the requested REA-based re-engineering option.

## Executive assessment

Keel is a strong competition prototype for Topic B. It implements the complete advisory narrative:
fact finding, C1–C5 profiling, product filtering, allocation, stress testing, goal planning, crash
rehearsal, human-confirmed simulated execution, an Advice Report, bilingual UI, audit chaining, and
optional FISCO BCOS anchoring. The design principle is unusually clear: the model speaks and
orchestrates, while deterministic Python computes every financial number and enforces suitability.

The repository is not yet production-ready. The web session model is prototype-grade: state and
confirmation tokens are held in memory, the signed state cookie is integrity-protected but readable,
and there is no authenticated user identity or CSRF token. Quantitative outputs are transparent, but
several inputs are proxies or assumptions rather than investable Chinese-market risk estimates. The
FISCO sender now uses the pending account nonce and serializes sends within a process; the live local
round-trip test passes after restoring all four chain nodes.

**Readiness score:** approximately **8.0/10 for the competition prototype** and **5.5/10 for a
regulated production service**. The competition score assumes the full suite remains green on the
submission machine and the demo uses replay mode as a fallback.

## China and sponsor alignment

The product target is China. The Western robo-advisors below are interaction and capability
references only; they are not the regulatory or product-market target for Keel.

The official Chinese competition site distinguishes strategic guidance, organizer, co-organizers and
technical guidance rather than presenting one generic “sponsor” list:

| Role | Organization | What this means for Keel |
|---|---|---|
| Strategic guidance | Shenzhen Municipal Financial Regulatory Bureau, Shenzhen University, WeBank | Lead with suitability, safe agent actions, consumer protection and practical banking integration. |
| Organizer | Shenzhen University WeBank FinTech College | Show an implementable student prototype with a clear path into a Chinese digital-bank product. |
| Co-organizers listed on the official site | iCAN Future (Beijing) Technology Co., Ltd.; Gouxiong Hui | Keep the demo understandable, measurable and suitable for a public innovation competition. |
| Technical guidance | CCF Digital Finance Branch; Tsinghua University Institute of FinTech; IEEE Computational Intelligence Society Singapore Chapter; IEEE Computational Intelligence Society Shenzhen Chapter | Expect questions about data, modelling validity, AI engineering and reproducibility. |
| Academic advisors / judges named on the official site | Qiang Yang, Li Wenrong, Li Jianqiang, Chai Yunpeng, Xiu Dacheng, Wolfgang Karl Härdle, Joshua Bongard, and others | Prepare for scrutiny of privacy, agent safety, portfolio mathematics, market assumptions and real-world deployment. |

This changes the pitch emphasis. The demo should show a **RMB/CNY Chinese retail investor**, Chinese
public funds and bank deposits/savings products, C1–C5/R1–R5 suitability, Chinese/English narration,
local auditability and a simulated bank workflow. Tax-loss harvesting, US ETF examples and Western
tax assumptions should be presented only as future research, never as current Chinese functionality.

The strongest sponsor-aligned extensions are:

- **WeBank / privacy:** a roadmap experiment using FATE-style federated learning to improve revealed
  risk-tolerance calibration without pooling raw client data. FATE was initiated by WeBank's AI
  department and supports federated learning and secure computation; it should remain a post-demo
  research module, not a last-minute dependency.
- **WeBank / controllable infrastructure:** keep FISCO BCOS anchoring as an optional proof layer, but
  make the nonce/idempotency path reliable before showing it live.
- **Financial regulator / suitability:** add a Chinese regulatory coverage matrix, freshness and
  source fields for every fund/rate, and an explicit “not a legal certification” boundary.
- **Academic finance reviewers:** show proxy limitations, fee/slippage exclusions, stress-vs-forecast
  separation, sensitivity bands and the deterministic calculation version in every report.

The official international-track announcement confirms the Topic B choice, English submission
requirement, WeBank/Tsinghua hosting relationship and 20 October 2026 deadline. The Chinese official
site provides the fuller sponsor, organizer and technical-guidance breakdown used above:
https://fintechathon.g-ican.com/ and
https://ird.oou.cmu.ac.th/2026-shenzhen-international-fintech-competition/.

## Evidence collected

| Check | Result | Interpretation |
|---|---:|---|
| `LLM_MODE=replay LIVE_MARKET=0 uv run pytest -q` | **156 passed** | Full suite is green, including the local FISCO anchor round-trip and tamper check. |
| `uv run python evals/redteam/run.py --strict` | **65/65** | All listed attack and benign cases pass in the current deterministic suite. |
| `LLM_MODE=replay uv run wealth-advisor demo` | **Pass** | CLI completes profile → comparison → allocation → stress → audit verification offline. |
| `uv run python -m compileall -q src api scripts evals` | **Pass** | No Python bytecode/parse errors found. |
| Live journey report | **30/30** | Existing report says 30 personas completed; median 14,378 tokens, 7 calls, 129.3 seconds. This is useful evidence but should be re-run after any prompt/tool change. |

The current repository contains 24 Chinese fund records, 14 fixed-income/deposit records, a curated
execution evidence pack, a presentation, a demo video, and a security self-assessment. These assets
make the submission reviewable rather than just a code drop.

## Topic B scorecard

| Competition dimension | Assessment | Strengths | Gaps that can cost points |
|---|---|---|---|
| Task completion (40%) | **32–35/40** | Full end-to-end path; chat and form share state; goal Monte Carlo; crash rehearsal; simulated execution; report export. | Median live journey is slow; free-tier quota can interrupt a live demo; browser-level journey is not automated in CI; no persistent multi-user account. |
| Security and compliance (30%) | **24–27/30** | Cn/Rn suitability in code; permission tiers; human-only token; PII redaction; tool validation; output grounding; rate limits; hash chain; red-team evidence. | Prompt-guard provider failure is fail-open to heuristics; no authenticated identity or CSRF token; state cookie is not encrypted; in-memory tokens/session store; simplified CSRC scope. |
| Innovation and interaction (30%) | **25–28/30** | Crash Rehearsal is a memorable behavioural signal; provenance popovers; bilingual UI; what-if goals; proactive market checks; FISCO alignment; report fingerprint. | Rebalancing is not yet a complete goal-aware operating loop; no household/whole-portfolio view, tax-aware logic, factor risk decomposition, or advisor review queue. |
| **Estimated total** | **81–90/100** | Strong prototype with a credible differentiator. | The score depends heavily on demo reliability and the judges' weighting of live task completion. |

## Product advantages

1. **A defensible model/code boundary.** The most important numbers are generated by tested Python
   functions. The LLM cannot choose a risk class, pass an arbitrary portfolio to the stress tool, or
   execute an order. This is much stronger than a prompt-only compliance claim.
2. **Suitability is visible and enforceable.** The lower of capacity and tolerance drives C1–C5;
   vulnerability flags cap the result; R1–R5 products are filtered server-side; above-class requests
   are blocked. The Advice Report exposes reason codes instead of only showing a score.
3. **Crash Rehearsal is a real interaction advantage.** It tests revealed behaviour on the client's
   proposed portfolio and can only lower the class. This gives judges a clear answer to “how do you
   measure behavioural risk beyond a questionnaire?”
4. **Execution has a credible human boundary.** A one-time token is issued by the UI, bound to the
   exact order summary, hashed, and consumed once. The model has no tool that creates or confirms the
   token.
5. **Evidence is unusually complete for a hackathon.** Audit JSONL, report fingerprinting, scenario
   transcripts, red-team results, journey results, and optional FISCO anchoring support the claims.
6. **Low operational complexity.** FastAPI plus plain HTML/CSS/JS avoids a frontend build chain and
   keeps the deterministic engine easy for judges to inspect. Replay mode removes API-key and quota
   risk from CI and the recorded demo.
7. **Good alignment with WeBank's ecosystem.** FISCO BCOS anchoring and the English/Chinese surface
   make the story relevant to the host while staying within a simulated account.

## Main shortcomings and risks

### P0 — no open blocker identified in this audit pass

FISCO nonce handling is fixed for the observed local failure: `_send()` obtains the pending nonce,
serializes sends in-process, and refreshes the nonce once after a `NonceCheckFail`. The full test suite
passed against the local four-node chain on 15 October 2026. Keep the chain-backed test in the release
check so future RPC or consensus changes cannot silently regress it.

### P1 — fix before judging or label clearly

**Prototype session security.** `ui/server.py` stores sessions and confirmation tokens in memory. The
state cookie is HMAC-signed and compressed, but not encrypted; a holder of their own cookie can decode
amount, age, profile, allocation, holdings, and order state. `STATE_COOKIE_SECRET` is generated randomly
when absent, so a cold start or a second worker cannot validate an old cookie. There is no user
authentication, CSRF token, persistent token revocation, or multi-worker coordination.

**Fix:** keep only an opaque session identifier in the browser, move state and token records to a
server-side store (Redis/PostgreSQL), require a stable secret from the environment, encrypt sensitive
fields at rest, add CSRF protection for state-changing routes, and bind confirmation to an authenticated
user/device. For the competition, put the current design in the known-risk slide and verify that
`STATE_COOKIE_SECRET` is set in the deployed environment.

**Prompt-guard availability is fail-open.** If the remote classifier errors, `PromptGuardClassifier`
returns `0.0` and relies on local heuristics. That is a reasonable availability choice for a prototype,
but the risk should be stated accurately: the classifier is not a hard security control. The red-team
suite exercises heuristics, not adversarial distribution shift.

**Fix:** make live classifier failure produce a visible degraded-security event, optionally reject
high-risk requests until a classifier is available, and expand the regression set with property-based
mutations and multilingual paraphrases. Keep server-side suitability and execution controls as the
last line of defence.

**Live latency and quota.** The reported median journey is 7 LLM calls, 14,378 tokens and 129.3 seconds.
That is acceptable for a recorded research demo but fragile under a free-tier quota, especially with a
30 RPM / 8K TPM provider limit.

**Fix:** precompute deterministic stages in the UI, make the live demo one short scripted journey,
cache the fact-finding/profile narration, expose a clear “replay mode” toggle, and show provider,
latency and token counters in the audit drawer. Do not claim the live path is low-latency until it is
measured on the submission environment.

**Market-data fitness is mixed.** The CN catalog contains real public funds, but the portfolio engine
uses US equity/REIT proxies, an approximate Treasury-duration bond series, World Bank gold, and a
50/50 blend of historical fund CAGR and an asset-class prior. The documentation discloses this, which
is good, but it limits the strength of claims about Chinese portfolio risk. The backtest also omits
fund fees, taxes, slippage and trading costs.

**Fix:** label every estimate with `as_of`, source, proxy status and freshness; add Chinese equity and
bond benchmarks where licensing permits; include a fee/slippage sensitivity view; and show a range or
confidence interval rather than a single expected return. Keep stress results deliberately separate
from forecasts.

**Regulatory scope is intentionally simplified.** The C1–C5/R1–R5 mapping is a defensible prototype
modelled on CSRC suitability principles, with MiFID II/FINRA as international references. It is not a
legal implementation of professional-investor treatment, complex products, record-retention periods,
dual recording, suitability exception workflows, or tax rules.

**Fix:** use the phrase “modelled on” consistently, have a domain reviewer sign off the mapping, add a
regulatory coverage table with explicit exclusions, and keep the simulated-account disclaimer on every
demo and exported report.

### P2 — post-submission product improvements

**No complete goal operating loop.** Goal Monte Carlo is present, but allocations are still primarily
class-based. Leading robo-advisors reduce risk as a goal approaches and monitor drift continuously.
Add a deterministic goal-specific glide path, multiple concurrent goals, contribution scheduling, and
an explanation of why a rebalance was proposed.

**Limited whole-portfolio context.** The current session plans the amount entered in the app. It does
not aggregate external holdings, household accounts, liabilities, taxes, or currency exposure. Add an
optional local-only household import with PII minimisation and a clear “unknown holdings” state.

**Risk analytics can go deeper.** Volatility, parametric VaR and three historical shocks are useful,
but factor contribution, expected shortfall, drawdown duration, liquidity-at-risk and scenario
comparison would make the output more useful to an advisor and more credible to finance academics.

**Testing is broad but not fully operational.** There are no browser automation tests for the actual
JS flow, no load/soak test for session caps, no dependency/SBOM scan in CI, and no test of a multi-worker
deployment. Add a Playwright smoke path, a small concurrency test for order tokens and anchors, and a
security scan that runs without external keys.

**Data and report lifecycle.** Market snapshots and fund metadata need a freshness dashboard and a
rebuild manifest. Advice reports should include a catalog version, market-data hash, calculation
version, and an explicit “data stale as of” indicator. This makes a later report reproducible after the
catalog changes.

## Benchmark against strong comparable products

The following are capability references, not claims that their proprietary implementations should be
copied.

| Product | Publicly documented capability | What Keel already has | What to adopt in Keel |
|---|---|---|---|
| **Vanguard Digital Advisor** | Goal timeline, risk tolerance, monitoring and rebalancing around goals. Source: https://ownyourfuture.vanguard.com/content/en/advice-profile/digital-advisor/faq.html | Goal projection and a risk profile. | Goal-specific glide path, scheduled reassessment, and a clear “on track / at risk” state. |
| **Wealthfront** | MPT portfolios personalised to risk/tax level, dividend reinvestment, rebalancing and automated tax-loss harvesting. Source: https://research.wealthfront.com/whitepapers/investment-methodology/ | Deterministic allocation, fees, simulated execution, market checks. | Account-type/tax profile, drift bands, tax-aware replacement pairs, and a user-visible reason for each rebalance. Chinese tax treatment must be reviewed before implementation. |
| **Schwab Intelligent Portfolios** | Questionnaire using goals, risk tolerance and timeline; 80+ portfolio variations; daily monitoring/rebalancing; goal tracker and optional tax-loss harvesting. Sources: https://www.schwab.com/intelligent-portfolios and https://www.schwab.com/automated-investing/goal-tracker | Questionnaire, allocation, goal Monte Carlo and stress tests. | Multiple goal buckets, policy variants, drift thresholds, and a “why this action now?” monitoring card. |
| **Betterment** | Reactive and proactive rebalancing, drift tolerance and goal-aware auto-adjust. Source: https://www.betterment.com/legal/auto-adjust-disclosure | Monitoring module and human confirmation. | A deterministic rebalance proposal queue with client confirmation and a goal glide path. |
| **BlackRock Aladdin Wealth** | Whole-portfolio view, proposal generation, risk/cost/tax analysis, scenario modelling, factor and security-level risk insights, next-best-action workflows. Sources: https://www.blackrock.com/aladdin/platforms/solutions/aladdin-wealth and https://www.blackrock.com/aladdin/platforms/products/aladdin-risk | Provenance, stress scenarios, Advice Report, proactive alerts. | Household aggregation, factor risk contributors, proposal comparison, and an advisor review queue. |

Keel's opportunity is to combine the consumer clarity of Vanguard/Wealthfront/Schwab/Betterment with
the auditability and human approval boundary that the commercial platforms expose mainly to advisors.
The best differentiator remains **proof-of-advice**, not a claim to outperform those products.

## REA feasibility and a safe re-engineering plan

REA describes itself as an MCP/tooling layer that lets a coding agent inspect JavaScript/Electron
applications, browser/runtime activity, and native binaries, then return evidence and limitations
before rebuilding a feature. The official setup is `npx rea-agents@latest setup`; the repository is
MIT-licensed. Sources: https://github.com/morluto/rea and https://rea.tools/.

### Feasibility

**Technically feasible as a development workflow, not as a runtime dependency.** Keel's plain JS UI,
FastAPI routes and deterministic Python engine are good targets for behavioural inspection. REA can
help map public onboarding flows, observe visible state transitions, and compare a rebuilt interaction
against a target. It cannot grant access to private broker logic, proprietary data, or an authenticated
client account. The result still needs to be reimplemented in Keel's Python/JS architecture and kept
inside the deterministic/compliance boundary.

### Recommended targets

1. **Goal onboarding and progress states** from publicly accessible Vanguard/Schwab/Betterment flows.
2. **Drift/rebalance explanation** from public product demos and documentation.
3. **Portfolio comparison and risk-contribution views** inspired by Aladdin's public advisor material.
4. **Keel's own UI**: use REA to map routes, browser state and visible data flows, then verify that no
   client facts, order tokens or hidden audit data enter the model prompt or browser markup.

### Guardrails

- Inspect only public pages, open-source code, or assets for which the team has permission.
- Do not bypass authentication, paywalls, anti-bot controls or technical restrictions.
- Do not copy source code, branding, text, proprietary models, private APIs or customer data.
- Record target URL/version, observation date, evidence digest, inferred behaviour and uncertainty.
- Rebuild the behaviour with Keel's own tests, reason codes, provenance and compliance controls.

### Suggested implementation sequence

| Phase | Deliverable | Acceptance test |
|---|---|---|
| 1. Benchmark capture | `docs/benchmarks/<product>.md` plus screenshots/DOM or source digests where permitted | A reviewer can reproduce the observation without credentials. |
| 2. Feature spec | State machine, inputs, outputs, failure states, regulatory assumptions | All financial calculations point to deterministic Python functions. |
| 3. Keel implementation | Goal glide path, drift proposal, or factor view behind existing API/UI | Same input gives the same result; every number has a provenance record. |
| 4. Safety integration | Suitability, loss-limit, PII, audit, human confirmation and kill-switch checks | Red-team and scenario tests cover the new path. |
| 5. Judge-ready demo | One short flow plus replay fallback | Completes under quota and remains understandable without live network access. |

## Prioritised 6-day improvement plan

The competition deadline shown on the official announcement is **20 October 2026, 23:59 Beijing time
(UTC+8)**. The plan below assumes a feature freeze before the deadline.

### Day 1: reliability gate

- Fix FISCO nonce/idempotency and add sequential/concurrent anchor tests.
- Run the full suite with and without a local chain; publish both results.
- Freeze the recorded demo path and verify its evidence hashes.

### Day 2: deployment/security gate

- Require `STATE_COOKIE_SECRET` in production and document the cold-start behaviour.
- Move the P0/P1 security limitations into the demo and security slide.
- Add a tiny browser smoke test for profile → allocation → confirm → report.

### Day 3: judge-facing quant clarity

- Add `catalog_version`, `market_data_as_of`, source hash and calculation version to reports.
- Show proxy labels, stale-data status, and a fee/slippage sensitivity toggle.
- Make the 2008 rehearsal and the above-class refusal the central demo narrative.

### Day 4: task-completion polish

- Reduce live calls in the scripted journey; cache narration and keep replay one click away.
- Add a visible latency/token/provider footer to the audit drawer.
- Re-run the 30-persona journey after the final prompt/tool changes.

### Day 5: differentiation

- Implement the smallest goal-aware glide-path or drift proposal feature.
- If time is insufficient, ship a clearly labelled REA-derived benchmark and an implementation plan
  rather than an untested partial trading feature.

### Day 6: submission audit

- Clean clone: `uv sync`, offline tests, red-team suite, CLI demo, UI startup.
- Verify no `.env`, keys, passport data or temporary FISCO account material is tracked.
- Check English-only submission artefacts and the 5-minute demo script.

## Final verdict

Keel is already a credible Topic B submission with a stronger safety and evidence story than a typical
LLM robo-advisor. Its winning story is: **the AI explains a suitability-checked plan, deterministic
code calculates it, a crash rehearsal tests the human, and only the human can confirm a simulated
order**. Prioritise reliability and deployment truthfulness over adding another model or another
portfolio optimiser. Fix the FISCO nonce path, make session security limitations explicit, and present
the proxy data honestly; then use REA as a controlled research tool to add goal-aware rebalancing and
whole-portfolio explanations after the core demo is stable.
