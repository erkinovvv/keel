# AGENTS.md

Full task brief: `docs/CODEX_PROMPT.md` — read it before any work.

- Python 3.12, managed with uv: `uv sync`, `uv run pytest`, `uv run wealth-advisor`.
- LLM: Groq free tier via the `openai` SDK (`base_url=https://api.groq.com/openai/v1`, env `GROQ_API_KEY`).
- Golden rule: the LLM never computes numbers. Risk scores, weights, returns, fees, stress losses come from deterministic, tested Python code; the LLM only quotes tool outputs.
- Security rules are enforced in code, not in prompts. Order execution requires a human confirmation token the LLM cannot produce.
- Tests must pass offline (`LLM_MODE=replay`), no API key.
- Never commit `.env`, keys, or real personal data. All text, code, docs in English.
