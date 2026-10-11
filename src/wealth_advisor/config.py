"""Environment-backed settings for the advisory agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ProviderConfig:
    """One OpenAI-compatible provider and its ordered, provider-specific key pool."""

    name: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...]
    api_key: str | None = None
    api_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    """Runtime settings with replay mode as the safe offline default."""

    llm_mode: str = "replay"
    groq_api_key: str | None = None
    groq_api_keys: tuple[str, ...] = ()
    cerebras_api_key: str | None = None
    cerebras_models: tuple[str, ...] = ("gpt-oss-120b",)
    primary_model: str = "openai/gpt-oss-120b"
    prompt_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"
    fallback_models: tuple[str, ...] = ("qwen/qwen3.8-27b", "openai/gpt-oss-20b")
    audit_log: Path = Path("logs/audit.jsonl")
    replay_file: Path = Path("tests/fixtures/replay.json")
    max_tool_steps: int = 8
    cash_rate: float = 0.035
    kill_switch: bool = False
    max_session_turns: int = 30
    max_order_amount: float = 100_000.0
    max_daily_order_amount: float = 250_000.0
    max_orders_per_session: int = 20
    cooling_off_days: int = 1
    simulated_cash: float = 1_000_000.0
    providers: tuple[ProviderConfig, ...] = ()

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "Settings":
        """Load settings without requiring a key, so CI can run fully offline."""

        if env_file:
            load_dotenv(env_file, override=False)
        fallback = tuple(
            model.strip()
            for model in os.getenv("GROQ_FALLBACK_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-20b").split(",")
            if model.strip()
        )
        groq_key = os.getenv("GROQ_API_KEY")
        cerebras_key = os.getenv("CEREBRAS_API_KEY")
        groq_pool = tuple(key.strip() for key in os.getenv("GROQ_API_KEYS", "").split(",") if key.strip())
        return cls(
            llm_mode=os.getenv("LLM_MODE", "replay").lower(),
            groq_api_key=groq_key,
            groq_api_keys=groq_pool,
            cerebras_api_key=cerebras_key,
            cerebras_models=tuple(model.strip() for model in os.getenv("CEREBRAS_MODELS", "gpt-oss-120b").split(",") if model.strip()),
            primary_model=os.getenv("GROQ_PRIMARY_MODEL", "openai/gpt-oss-120b"),
            prompt_guard_model=os.getenv("PROMPT_GUARD_MODEL", "meta-llama/llama-prompt-guard-2-86m"),
            fallback_models=fallback,
            audit_log=Path(os.getenv("AUDIT_LOG", "logs/audit.jsonl")),
            replay_file=Path(os.getenv("REPLAY_FILE", "tests/fixtures/replay.json")),
            max_tool_steps=int(os.getenv("MAX_TOOL_STEPS", "8")),
            cash_rate=float(os.getenv("CASH_RATE", "0.035")),
            kill_switch=os.getenv("WEALTH_ADVISOR_KILL_SWITCH", "false").lower() in {"1", "true", "yes"},
            max_session_turns=int(os.getenv("MAX_SESSION_TURNS", "30")),
            max_order_amount=float(os.getenv("MAX_ORDER_AMOUNT", "100000")),
            max_daily_order_amount=float(os.getenv("MAX_DAILY_ORDER_AMOUNT", "250000")),
            max_orders_per_session=int(os.getenv("MAX_ORDERS_PER_SESSION", "20")),
            cooling_off_days=int(os.getenv("COOLING_OFF_DAYS", "1")),
            simulated_cash=float(os.getenv("SIMULATED_CASH", "1000000")),
        )
