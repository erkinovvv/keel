"""Human-readable labels for questionnaire keys and reason codes shown in the UI."""

from __future__ import annotations

import re

QUESTION_LABELS: dict[str, str] = {
    "horizon": "How long can this money stay invested?",
    "income_stability": "How stable is your income?",
    "emergency_fund": "How many months of expenses do you hold in cash?",
    "invested_share": "What share of your net worth is this investment?",
    "liquidity_need": "When might you need to withdraw part of this money?",
    "drawdown_reaction": "Your portfolio falls 20% in a month. What do you do?",
    "experience": "How experienced are you with funds, bonds or shares?",
    "goal": "What is the main goal of this money?",
}

OPTION_LABELS: dict[str, str] = {
    "under_1y": "Less than 1 year",
    "1_3y": "1–3 years",
    "3_7y": "3–7 years",
    "7_10y": "7–10 years",
    "over_10y": "More than 10 years",
    "unstable": "Irregular / uncertain",
    "mixed": "Partly stable",
    "stable": "Stable salary or pension",
    "none": "None",
    "3_6_months": "3–6 months",
    "over_6_months": "More than 6 months",
    "over_75": "More than 75%",
    "50_75": "50–75%",
    "25_50": "25–50%",
    "under_25": "Less than 25%",
    "sell_all": "Sell everything",
    "reduce": "Sell some to limit losses",
    "hold": "Hold and wait",
    "buy_more": "Buy more at lower prices",
    "basic": "Basic (deposits, a few funds)",
    "good": "Good (several years investing)",
    "advanced": "Advanced (professional / active investor)",
    "preserve": "Preserve capital",
    "income": "Regular income",
    "growth": "Long-term growth",
    "aggressive_growth": "Maximum growth, high risk accepted",
}

CLASS_NAMES = {
    1: "Conservative",
    2: "Moderately Conservative",
    3: "Balanced",
    4: "Growth",
    5: "Aggressive",
}

FLAG_LABELS = {
    "AGE_70_PLUS": "Age 70+ — risk level capped for client protection",
    "NO_EMERGENCY_FUND": "No emergency fund — build a cash buffer first",
    "BORROWED_MONEY": "Investing borrowed money — risk level capped",
    "SHORT_HORIZON": "Horizon under 1 year — only capital-preserving products",
}


def humanize(key: str) -> str:
    """Return a readable label for a questionnaire option key, falling back to the key."""

    return OPTION_LABELS.get(key, key.replace("_", " ").capitalize())


def question_label(key: str) -> str:
    return QUESTION_LABELS.get(key, key.replace("_", " ").capitalize())


def explain_reason(code: str) -> str:
    """Translate a deterministic reason code into one plain-English sentence."""

    if match := re.fullmatch(r"SUITABLE_C(\d)_R(\d)", code):
        investor, product = match.groups()
        return f"Suitable: product risk R{product} does not exceed your risk class C{investor}."
    if code == "RISK_ADJUSTED_RETURN_NET_OF_FEES":
        return "Best expected return per unit of risk, after fees, within its asset class."
    if code == "VULNERABILITY_CAP_APPLIED":
        return "A client-protection cap lowered your risk class (see flags)."
    for question in sorted(QUESTION_LABELS, key=len, reverse=True):
        prefix = question.upper() + "_"
        if code.startswith(prefix):
            answer = code[len(prefix):].lower()
            return f"{question_label(question)} → {humanize(answer)}"
    return code.replace("_", " ").capitalize()
