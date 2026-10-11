# From prototype to service: research and plan

Two inputs: (1) Anthropic's engineering guidance on agents and tools (offline archive of their
docs and engineering blog), (2) a production-readiness audit of this repository against common
service practice (twelve-factor config, OWASP-style web hardening, observability, CI).

## 1. Agent quality — what Anthropic's guidance says, applied to us

| # | Guidance (source) | What we change | Owner |
|---|---|---|---|
| A1 | "Poka-yoke your tools. Change the arguments so that it is harder to make mistakes." (*Building effective agents*) | Unit-explicit parameter names (`max_loss_fraction`, `amount_cny`), one accepted unit per field | Codex |
| A2 | "instead of a parameter named `user`, try a parameter named `user_id`"; descriptions of 3–4 sentences (*Writing tools for agents*, tool-use docs) | Longer tool descriptions with one example call each | Codex |
| A3 | Schema strictness does not enforce numeric ranges (structured-outputs docs) | Keep range checks in Python and return an actionable error: "max_loss=20 looks like a percent; pass 0.20" | Codex |
| A4 | "prompt-engineer your error responses to clearly communicate specific and actionable improvements" (*Writing tools*) | Tool errors name the field, the value and the fix | Codex |
| A5 | "Avoid overly strict verifiers that reject correct responses due to spurious differences like formatting" (*Writing tools*; *Demystifying evals*) | Output guard normalises %, rounding, Unicode spaces, questionnaire numbers (in progress) | Codex |
| A6 | Generator plus evaluator loop: the generator needs "something concrete to iterate against" (*Building effective agents*; *Harness design*) | A blocked reply goes back once with the exact ungrounded figures before any fallback | Codex |
| A7 | "Explicitly give Claude permission to admit uncertainty" (hallucination guide) | Prompt: "if a figure is not in a tool result, say you will compute it" | Codex |
| A8 | "return only high signal information"; concise results used about a third of the tokens (*Writing tools*) | Tool results carry formatted display strings the model can quote verbatim; drop raw arrays | Codex |
| A9 | Clear old raw tool results; keep structured notes outside the window (*Context engineering*) | Keep a compact client-profile JSON in the system message; trim old tool outputs | Codex |
| A10 | Static content first for caching; adding tools mid-conversation breaks the cached prefix (prompt-caching docs) | Keep the tool list order stable; append stage tools, never reorder | Codex |
| A11 | A role, reasons and 3–5 examples beat rule lists (prompting best practices; *Context engineering*) | Rewrite the advisor prompt: one-line role, short reasons, 3 example exchanges | Codex |
| A12 | "Don't put your own instructions in tool results" (jailbreak mitigation docs) | Audit tool outputs: data only, no steering text | Codex |
| A13 | Test both directions; one-sided evals create one-sided optimisation (*Demystifying evals*) | Add benign near-miss cases to the red-team suite and report the guard's false-positive rate | Claude |
| A14 | pass^k for customer-facing agents; grade outcomes, not the path; separate rubric judges; "Read the transcripts!" (*Demystifying evals*) | Journey eval: pass^3 on a subset, tone rubric, transcript review of every failure | Claude |
| A15 | Agents "reliably skew positive when grading their own work" (*Harness design*) | Keep the output guard deterministic and separate from the responder | — (already so) |

## 2. Service hardening — audit of this repository

| Area | Finding | Status / owner |
|---|---|---|
| Audit integrity under concurrency | Two sessions on the shared log broke the hash chain | **Fixed** (per-file lock + flock, real last hash read from disk, session tag) · Claude |
| Session storage | Sessions live in an unbounded in-memory dict: no expiry, unlimited creation | Add TTL eviction, a cap and a per-IP creation limit · Claude |
| Health and version | No health endpoint | Add `/healthz` (version, catalog, chain, LLM mode) · Claude |
| Web hardening | No security headers | Add CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy` · Claude |
| Configuration | Env-driven settings, `.env.example` | OK; document every variable in README · Claude |
| Lint and types | No linter config; 62 ruff findings | Add ruff config, fix in a quiet window (touches everyone's files) · both |
| CI | No pipeline | GitHub Actions: `uv sync`, `pytest`, red-team `--strict` · Claude |
| Packaging | No container | Dockerfile for the web app (FISCO chain stays a separate script) · Claude |
| Offline experience | Replay chat answers with a placeholder | Honest "live chat needs a key" message (queued) · Codex |
| Secrets | Keys only in `.env`, never logged; key index only in audit | OK |
