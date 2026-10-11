"""Human-readable labels for questionnaire keys and reason codes shown in the UI."""

from __future__ import annotations

import re
from contextvars import ContextVar

# Current UI language, set per request by the web server ("en" or "zh").
LANG: ContextVar[str] = ContextVar("lang", default="en")

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
    "within_1d": "Any day",
    "within_7d": "Within a week",
    "within_30d": "Within a month",
    "over_30d": "Not for at least a month",
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


QUESTION_LABELS_ZH: dict[str, str] = {
    "horizon": "这笔钱可以投资多长时间？",
    "income_stability": "您的收入稳定吗？",
    "emergency_fund": "您手头的现金够支付几个月的开支？",
    "invested_share": "这笔投资占您净资产的比例是多少？",
    "liquidity_need": "您什么时候可能需要取出其中一部分？",
    "drawdown_reaction": "如果您的投资一个月内下跌20%，您会怎么做？",
    "experience": "您对基金、债券或股票的投资经验如何？",
    "goal": "这笔钱的主要目标是什么？",
}

OPTION_LABELS_ZH: dict[str, str] = {
    "under_1y": "少于1年", "1_3y": "1–3年", "3_7y": "3–7年", "7_10y": "7–10年", "over_10y": "10年以上",
    "within_1d": "随时", "within_7d": "一周内", "within_30d": "一个月内", "over_30d": "至少一个月内不动用",
    "unstable": "不稳定", "mixed": "部分稳定", "stable": "稳定的工资或养老金",
    "none": "没有", "3_6_months": "3–6个月", "over_6_months": "6个月以上",
    "over_75": "超过75%", "50_75": "50–75%", "25_50": "25–50%", "under_25": "少于25%",
    "sell_all": "全部卖出", "reduce": "卖出一部分以控制损失", "hold": "继续持有，耐心等待", "buy_more": "逢低加仓",
    "basic": "入门（存款和少量基金）", "good": "较好（投资多年）", "advanced": "资深（专业或活跃投资者）",
    "preserve": "保本", "income": "稳定收益", "growth": "长期增值", "aggressive_growth": "追求最大收益，接受高风险",
}

CLASS_NAMES_ZH = {1: "保守型", 2: "稳健型", 3: "平衡型", 4: "成长型", 5: "进取型"}

FLAG_LABELS_ZH = {
    "AGE_70_PLUS": "年满70岁：为保护客户，风险等级已设上限",
    "NO_EMERGENCY_FUND": "没有应急资金：请先建立现金储备",
    "BORROWED_MONEY": "使用借款投资：风险等级已设上限",
    "SHORT_HORIZON": "投资期限少于1年：仅适合保本类产品",
}


def lang() -> str:
    return "zh" if LANG.get() == "zh" else "en"


def class_name(investor_class: int) -> str:
    return (CLASS_NAMES_ZH if lang() == "zh" else CLASS_NAMES)[investor_class]


def flag_label(flag: str) -> str:
    return (FLAG_LABELS_ZH if lang() == "zh" else FLAG_LABELS).get(flag, flag)


def humanize(key: str) -> str:
    """Return a readable label for a questionnaire option key, falling back to the key."""

    if lang() == "zh" and key in OPTION_LABELS_ZH:
        return OPTION_LABELS_ZH[key]
    return OPTION_LABELS.get(key, key.replace("_", " ").capitalize())


def question_label(key: str) -> str:
    if lang() == "zh" and key in QUESTION_LABELS_ZH:
        return QUESTION_LABELS_ZH[key]
    return QUESTION_LABELS.get(key, key.replace("_", " ").capitalize())


# Short noun labels for the "why this class" list, so each line reads "Label: answer".
REASON_LABELS = {
    "horizon": ("Investment horizon", "投资期限"),
    "income_stability": ("Income", "收入"),
    "emergency_fund": ("Cash reserve", "备用现金"),
    "invested_share": ("Share of your net worth", "占净资产比例"),
    "liquidity_need": ("When you may need the money", "用款时间"),
    "drawdown_reaction": ("If it fell 20% in a month", "若一个月内下跌20%"),
    "experience": ("Experience", "投资经验"),
    "goal": ("Goal", "投资目标"),
}


FIXED_REASONS = {
    "RISK_ADJUSTED_RETURN_NET_OF_FEES": ("Best expected return per unit of risk, after fees, within its asset class.", "在同类资产中，扣除费用后单位风险的预期收益最高。"),
    "REHEARSAL_HELD": ("You held your portfolio through the 2008 crash rehearsal.", "在2008年危机演练中，您坚持持有了投资组合。"),
    "REHEARSAL_SOLD_WITHIN_CLASS": ("You sold during the crash rehearsal, at a loss your risk class already allows for.", "您在危机演练中卖出，但亏损幅度仍在您的风险等级允许范围内。"),
    "VULNERABILITY_CAP_APPLIED": ("A client-protection cap lowered your risk class (see flags).", "客户保护规则降低了您的风险等级（见提示）。"),
    "LIQUIDITY_SLEEVE": ("Part of the portfolio is kept in assets you can withdraw quickly, matching when you may need the money.", "根据您的用款时间，组合中保留了一部分可快速取用的资产。"),
    "STRESS_LIMIT_APPLIED": ("Risk was reduced so the worst historical loss stays within the limit you gave us.", "已降低风险，使历史最差情景下的亏损不超过您设定的上限。"),
}


def explain_reason(code: str) -> str:
    """Translate a deterministic reason code into one plain sentence in the current UI language."""

    zh = lang() == "zh"
    if match := re.fullmatch(r"SUITABLE_C(\d)_R(\d)", code):
        investor, product = match.groups()
        return f"适当性匹配：产品风险R{product}不高于您的风险等级C{investor}。" if zh else f"Suitable: product risk R{product} does not exceed your risk class C{investor}."
    if match := re.fullmatch(r"REVEALED_TOLERANCE_C(\d)", code):
        return f"在危机演练中您在下跌时卖出，因此风险等级下调为C{match.group(1)}。" if zh else f"In the crash rehearsal you sold during the fall, so your risk class was lowered to C{match.group(1)}."
    if code in FIXED_REASONS:
        return FIXED_REASONS[code][1 if zh else 0]
    for question in sorted(QUESTION_LABELS, key=len, reverse=True):
        prefix = question.upper() + "_"
        if code.startswith(prefix):
            answer = code[len(prefix):].lower()
            label = REASON_LABELS.get(question, (question_label(question),) * 2)[1 if zh else 0]
            return f"{label}{'：' if zh else ': '}{humanize(answer)}"
    return code.replace("_", " ").capitalize()
