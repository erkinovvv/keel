# Wealth Advisory Agent

FinTechathon 2026 Topic B prototype: a deterministic, explainable wealth-advisory workflow with an LLM conversation layer.

## M1 quickstart

```bash
uv sync
cp .env.example .env
uv run pytest
uv run wealth-advisor
```

The default `LLM_MODE=replay` requires no API key. Set `LLM_MODE=live` and `GROQ_API_KEY` to use the OpenAI-compatible Groq endpoint. All portfolio numbers come from Python tools; the LLM only orchestrates and explains tool results.

## M1 components

- `profiling.py`: capacity and tolerance scores, C1–C5 suitability class, reason codes, vulnerability caps, and 12-month expiry.
- `catalog.py`: validated mock catalog, suitability filtering, net-return comparison, Sharpe-like score, and fee drag.
- `allocation.py`: strategic weights, suitable product ranking, 35% product cap, cash buffer, correlation-based volatility, and 95% one-year VaR.
- `stress.py`: 2008 GFC, 2020 COVID, 2022 rate shock, and custom scenarios.
- `llm.py` and `agent.py`: Groq fallback chain plus offline replay and bounded explicit tool loop.
- `audit.py`: append-only JSONL records with a tamper-evident hash chain.

Run `uv run wealth-advisor --verify-audit` to verify the configured audit log.
