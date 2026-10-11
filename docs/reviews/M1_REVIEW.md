# M1 Review (by Claude) — fix before / during M2

Baseline commit: `4de4421`. Tests: 17 passed. Ordered by severity.

## Critical — compliance / integrity

1. **Suitability bypass via tool args** (`tools.py` CompareArgs/AllocationArgs). `investor_class`
   is supplied by the LLM, so a jailbroken or confused model can pass `investor_class=5` for a C2
   client and get R5 products recommended. Fix: introduce a server-side **`AdvisorSession`**
   state; `investor_class` comes only from the stored, unexpired profile. Remove it from LLM-facing
   schemas. If no profile exists, comparison/allocation tools return an error asking to profile first.
2. **LLM round-trips the whole allocation into `stress_test`** (`StressArgs.allocation`). The model
   can alter weights/amounts before the stress test (numbers no longer come from code) and it costs
   many tokens under the 8K TPM limit. Fix: store allocations in session state, tools take
   `allocation_id` (or "latest"), results reference ids.

## High — robustness with free Groq models

3. **Tool errors crash the loop** (`agent.py`). pydantic `ValidationError` / `ValueError` /
   unknown tool / malformed JSON args (`json.loads` in `llm.py:81`) propagate and kill the session.
   Fix: catch, audit, and return `{"error": "...", "hint": "..."}` as the tool message so the model
   can self-correct; count failed calls toward max steps.
4. **History is not kept between turns and trimming can orphan tool messages.** `run()` does not
   return/update history, so there is no real multi-turn dialogue; `history[-6:]` can start with a
   `tool` message whose `assistant.tool_calls` was cut → Groq 400. Fix: `AdvisorSession` owns
   `messages`; trim on turn boundaries only; keep a compact structured client-state summary
   (profile class, amount, horizon, latest allocation id) injected into the system message.
5. **Fallback chain only on 429.** 404 (model decommissioned), 5xx, timeouts should also fall
   through to the next model. On 429, try the next model immediately; sleep on `retry-after` only
   when the whole chain is exhausted (bounded, e.g. ≤ 20 s). Create the `OpenAI` client once.
6. **CLI is a scripted demo, not an advisor.** M1 required "CLI that runs the full flow with the
   LLM". Add an interactive chat loop (`uv run wealth-advisor chat`) on top of `AdvisorSession`;
   keep the current scripted run as `uv run wealth-advisor demo`.

## Medium — finance correctness / brief alignment

7. **Min-investment can be violated after the cap split** (`allocation._select_holdings`): the
   eligibility check uses `target / count` but weights are assigned `min(0.35, remaining)`, so the
   last product can get less than its minimum. Fix: split equally (`target / count`, always ≤ cap)
   or re-check each final amount.
8. **No volatility targeting / mean-variance step** (brief §6.3). Currently strategic weights +
   greedy split. Add a small numpy refinement: within ±10pp of strategic weights per asset class,
   maximise net return − λ·variance subject to all constraints and a per-class target-vol band;
   document in `docs/ALGORITHM.md` section owned by Claude (just tell me the math/params).
9. **12-month lock-up deposit chosen without a liquidity question.** `CASH-DEP` (365 days) ranks
   first because its volatility is 0 → floored to 0.01. Add a `liquidity_need` questionnaire item
   (brief asks for 8–10 questions; we have 7) and default `liquidity_days` from it.
10. **Custom stress shocks unvalidated** — clamp to [-1.0, +1.0] per asset class.
11. VaR is parametric zero-mean — fine, but name it `var_95_1y_parametric` and state assumption in output.
12. Config env names ≠ brief (`GROQ_PRIMARY_MODEL` vs `LLM_MODEL`) — fine, keep yours, I updated nothing.

## Interface contract for the UI (Claude is building `src/wealth_advisor/ui/`)

Please expose this (names can differ slightly — tell me if so):

```python
class AdvisorSession:
    def __init__(self, settings: Settings | None = None, tier: PermissionTier = ...): ...
    state: SessionState          # profile, allocation(s), stress results, draft orders, account
    def send(self, user_message: str) -> str        # one full agent turn, guards applied
    def confirm_order(self, order_id: str, token: str) -> dict   # human-only path
```

## Ownership (to avoid edit conflicts)

- **Claude owns:** `src/wealth_advisor/ui/**`, `docs/**` (except this review file), the deck.
- **Codex owns:** everything else. Don't edit Claude's files; ask in your report if you need a change.
