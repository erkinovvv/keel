"""Deterministic input, tool-output, PII, and rate-limit controls."""

from __future__ import annotations

import re
import time
import unicodedata
from base64 import b64decode
from dataclasses import dataclass
from threading import Lock
from typing import Callable

from .audit import AuditLogger
from .config import Settings


_LEETSPEAK = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "@": "a", "$": "s"})
_BASE64_CHUNK = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/])")
_SPACED_LETTERS = re.compile(r"(?<!\w)(?:[A-Za-z]\s+){3,}[A-Za-z](?!\w)")


def _collapse_spaced_letters(text: str) -> str:
    def collapse(match: re.Match[str]) -> str:
        words = re.split(r"\s{2,}", match.group(0))
        return " ".join("".join(re.findall(r"[A-Za-z]", word)) for word in words)

    return _SPACED_LETTERS.sub(collapse, text)


def _decoded_base64(text: str) -> list[str]:
    decoded: list[str] = []
    for match in _BASE64_CHUNK.finditer(text):
        try:
            candidate = b64decode(match.group(0), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if candidate.strip():
            decoded.append(candidate)
    return decoded


def _normalised_candidates(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    candidates = [normalized, normalized.translate(_LEETSPEAK), _collapse_spaced_letters(normalized)]
    for decoded in _decoded_base64(normalized):
        candidates.extend((decoded.casefold(), decoded.casefold().translate(_LEETSPEAK)))
    return tuple(candidates)


_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous|disregard\s+(?:the\s+)?system|forget\s+everything\s+(?:above|before)", re.I),
    re.compile(r"reveal\s+(?:the\s+)?system\s+prompt|show\s+(?:the\s+)?hidden\s+instructions|(?:display|show).{0,20}(?:system|prompt)", re.I),
    re.compile(r"call\s+the\s+tool|use\s+function|buy\s+.+all\s+cash|tool\s+calls?\s+that\s+create\s+orders", re.I),
    re.compile(r"(?:suitability|compliance|risk)\s+(?:checks?\s+)?(?:are\s+)?(?:disabled|off|turned\s+off)|(?:skip|bypass)\s+(?:the\s+)?(?:risk|suitability|compliance)", re.I),
    re.compile(r"(?:^|[\n<])\s*(?:/?(?:system|developer|assistant|user))(?:\s*>|\s*:)", re.I),
    re.compile(r"pretend\s+.+(?:previous\s+instructions|real\s+instruction|skip\s+(?:the\s+)?risk)|role[- ]?play\b.+(?:regulation|borrowed\s+money|buy)|(?:novel|story)\b.+(?:bypass|suitability).+(?:step\s+by\s+step|explain)|act\s+as\s+(?:the\s+)?developer\s+mode|developer\s+mode.+(?:off|no\s+rules)|\bdan\b.+(?:no\s+rules|whatever\s+the\s+user)", re.I),
    re.compile(r"忽略.*(?:之前|所有).*(?:指令|说明)|(?:显示|透露|告诉).*(?:系统|提示词|指令)|(?:所有|全部).*(?:钱|资金).*(?:买|投入)", re.I),
    re.compile(r"игнорируй.*предыдущ|системн.*(?:промпт|инструкц)|купи.*все.*деньги", re.I),
    re.compile(r"oldingi.*(?:e['’]?tiborsiz|etiborsiz).*ko['’]?rsatmalar|barcha.*pul.*(?:fond|texnologiya)", re.I),
    re.compile(r"ignora.*instrucciones.*(?:anteriores|sistema)|muestra.*(?:prompt|sistema)", re.I),
    re.compile(r"(?:assistant|system|model).*(?:must|should|tell|recommend).*(?:guaranteed|return|fund|product)|(?:guaranteed|certain)\s+to\s+(?:return|profit)", re.I),
)
_PII_PATTERNS = (
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.I)),
    ("PASSPORT", re.compile(r"\bpassport\b(?:\s+(?:number|no\.?))?(?:\s+is\s+|\s*[:#-]\s*|\s+)(?=[A-Z0-9-]*\d)[A-Z0-9-]{5,}\b", re.I)),
    ("NATIONAL_ID", re.compile(r"\b(?:national\s+id|id\s+number)\b(?:\s+is\s+|\s*[:#-]\s*|\s+)(?=[A-Z0-9-]*\d)[A-Z0-9-]{5,}\b", re.I)),
    ("PHONE", re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)")),
    ("CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
)


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    text: str
    reasons: tuple[str, ...]
    pii_redacted: bool = False
    injection_score: float = 0.0


def redact_pii(text: str) -> tuple[str, tuple[str, ...]]:
    """Replace direct identifiers before text can enter the model context."""

    redacted = text
    found: list[str] = []
    for label, pattern in _PII_PATTERNS:
        redacted, count = pattern.subn(f"[{label}_REDACTED]", redacted)
        if count:
            found.append(label)
    return redacted, tuple(found)


def _injection_score(text: str) -> tuple[float, tuple[str, ...]]:
    candidates = _normalised_candidates(text)
    reasons = tuple(
        f"INJECTION_HEURISTIC_{index}"
        for index, pattern in enumerate(_INJECTION_PATTERNS, start=1)
        if any(pattern.search(candidate) for candidate in candidates)
    )
    return min(1.0, 0.45 * len(reasons)), reasons


def input_guard(text: str, classifier: Callable[[str], float] | None = None) -> GuardDecision:
    """Redact PII and block high-confidence prompt-injection attempts."""

    sanitized, pii_types = redact_pii(text)
    heuristic_score, injection_reasons = _injection_score(sanitized)
    classifier_score = max(0.0, min(1.0, classifier(sanitized))) if classifier else 0.0
    score = max(heuristic_score, classifier_score)
    reasons = tuple(f"PII_REDACTED_{kind}" for kind in pii_types) + injection_reasons
    return GuardDecision(not injection_reasons and classifier_score < 0.8, sanitized, reasons, bool(pii_types), score)


def tool_output_guard(text: str) -> GuardDecision:
    """Reject instructions embedded in catalog or other tool-returned text."""

    score, reasons = _injection_score(text)
    return GuardDecision(not reasons, text, reasons, False, score)


class RateLimiter:
    """Small thread-safe fixed-window limiter for session turns."""

    def __init__(self, max_calls: int = 30, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: list[float] = []
        self._lock = Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            self._calls = [started for started in self._calls if now - started < self.window_seconds]
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(now)
            return True


class PromptGuardClassifier:
    """Optional live Groq classifier; replay mode relies only on local heuristics."""

    def __init__(self, settings: Settings, audit: AuditLogger | None = None):
        self.settings = settings
        self.audit = audit
        self._client = None

    def score(self, text: str) -> float:
        if self.settings.llm_mode != "live" or not self.settings.groq_api_key:
            return 0.0
        try:
            from openai import OpenAI

            if self._client is None:
                self._client = OpenAI(api_key=self.settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
            response = self._client.chat.completions.create(
                model=self.settings.prompt_guard_model,
                messages=[{"role": "user", "content": text}],
                temperature=0,
            )
            raw = (response.choices[0].message.content or "0").strip()
            lowered = raw.casefold()
            if "malicious" in lowered or "unsafe" in lowered or "jailbreak" in lowered:
                score = 1.0
            elif "benign" in lowered or "safe" in lowered:
                score = 0.0
            else:
                match = re.search(r"(?:0(?:\.\d+)?|1(?:\.0+)?)", raw)
                if not match:
                    raise ValueError(f"unrecognised Prompt Guard label: {raw!r}")
                score = float(match.group(0))
            if self.audit:
                self.audit.append("prompt_guard_call", {"model": self.settings.prompt_guard_model, "score": score, "label": raw})
            return max(0.0, min(1.0, score))
        except Exception as exc:
            if self.audit:
                body = getattr(exc, "body", None)
                response_body = getattr(getattr(exc, "response", None), "text", None)
                self.audit.append("prompt_guard_error", {"error": type(exc).__name__, "body": body if body is not None else response_body or str(exc)})
            return 0.0
