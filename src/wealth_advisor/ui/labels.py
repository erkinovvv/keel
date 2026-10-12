"""Human-readable labels for questionnaire keys and reason codes shown in the UI."""

from __future__ import annotations

import re
from contextvars import ContextVar

# Current UI language, set per request by the web server ("en" or "zh").
LANG: ContextVar[str] = ContextVar("lang", default="en")

QUESTION_LABELS: dict[str, str] = {
    "horizon": "How long can you leave this money invested?",
    "income_stability": "How steady is your income?",
    "emergency_fund": "How many months could you live on your savings?",
    "invested_share": "How much of everything you own is this money?",
    "liquidity_need": "When might you need some of this money back?",
    "drawdown_reaction": "Imagine it drops 20% in one month. What would you do?",
    "experience": "How much have you invested before?",
    "goal": "What do you want this money to do?",
}

OPTION_LABELS: dict[str, str] = {
    "under_1y": "Less than 1 year",
    "1_3y": "1 to 3 years",
    "3_7y": "3 to 7 years",
    "7_10y": "7 to 10 years",
    "over_10y": "More than 10 years",
    "within_1d": "Any day",
    "within_7d": "Within a week",
    "within_30d": "Within a month",
    "over_30d": "Not in the next month",
    "unstable": "Irregular",
    "mixed": "Fairly steady",
    "stable": "Steady salary or pension",
    "none": "I have no savings set aside",
    "3_6_months": "3 to 6 months",
    "over_6_months": "More than 6 months",
    "over_75": "More than three quarters",
    "50_75": "Half to three quarters",
    "25_50": "A quarter to a half",
    "under_25": "Less than a quarter",
    "sell_all": "Sell everything",
    "reduce": "Sell some",
    "hold": "Wait it out",
    "buy_more": "Buy more while it is cheap",
    "basic": "A little: deposits, a few funds",
    "good": "Quite a lot: several years",
    "advanced": "I invest professionally or trade often",
    "preserve": "Keep it safe",
    "income": "Pay me a regular income",
    "growth": "Grow over the long term",
    "aggressive_growth": "Grow as much as possible, big swings are fine",
}

CLASS_NAMES = {
    1: "Conservative",
    2: "Careful",
    3: "Balanced",
    4: "Growth",
    5: "Aggressive",
}

FLAG_LABELS = {
    "AGE_70_PLUS": "Because you are 70 or older, we keep your risk lower to protect you.",
    "NO_EMERGENCY_FUND": "You have no savings set aside, so we keep your risk lower. Build a cash buffer first.",
    "BORROWED_MONEY": "Part of this money is borrowed, so we keep your risk lower.",
    "SHORT_HORIZON": "You may need this money within a year, so we only suggest very safe funds.",
}


QUESTION_LABELS_ZH: dict[str, str] = {
    "horizon": "这笔钱可以投资多久？",
    "income_stability": "您的收入稳定吗？",
    "emergency_fund": "您的存款够生活几个月？",
    "invested_share": "这笔钱占您全部资产的多少？",
    "liquidity_need": "您什么时候可能要取回一部分？",
    "drawdown_reaction": "假如一个月内跌了20%，您会怎么做？",
    "experience": "您以前投资过吗？",
    "goal": "您希望这笔钱做什么？",
}

OPTION_LABELS_ZH: dict[str, str] = {
    "under_1y": "不到1年", "1_3y": "1到3年", "3_7y": "3到7年", "7_10y": "7到10年", "over_10y": "10年以上",
    "within_1d": "随时", "within_7d": "一周内", "within_30d": "一个月内", "over_30d": "一个月内不用",
    "unstable": "不固定", "mixed": "比较稳定", "stable": "稳定的工资或养老金",
    "none": "没有存款", "3_6_months": "3到6个月", "over_6_months": "6个月以上",
    "over_75": "超过四分之三", "50_75": "一半到四分之三", "25_50": "四分之一到一半", "under_25": "不到四分之一",
    "sell_all": "全部卖出", "reduce": "卖出一部分", "hold": "耐心等待", "buy_more": "趁便宜多买一些",
    "basic": "一点点：存款和少量基金", "good": "比较多：投资多年", "advanced": "专业投资或经常交易",
    "preserve": "保住本金", "income": "带来稳定收入", "growth": "长期增值", "aggressive_growth": "尽量多赚，能接受大起大落",
}

CLASS_NAMES_ZH = {1: "保守型", 2: "稳健型", 3: "平衡型", 4: "成长型", 5: "进取型"}

FLAG_LABELS_ZH = {
    "AGE_70_PLUS": "您已年满70岁，为保护您，我们降低了风险。",
    "NO_EMERGENCY_FUND": "您还没有存款，所以我们降低了风险。建议先存一笔备用金。",
    "BORROWED_MONEY": "这笔钱中有借来的部分，所以我们降低了风险。",
    "SHORT_HORIZON": "您一年内可能要用这笔钱，所以只推荐非常稳妥的基金。",
}

# Product risk levels R1-R5 in plain words (CSRC wording in Chinese).
RISK_NAMES = {1: "low risk", 2: "low to medium risk", 3: "medium risk", 4: "medium to high risk", 5: "high risk"}
RISK_NAMES_ZH = {1: "低风险", 2: "中低风险", 3: "中风险", 4: "中高风险", 5: "高风险"}


def lang() -> str:
    return "zh" if LANG.get() == "zh" else "en"


def class_name(investor_class: int) -> str:
    return (CLASS_NAMES_ZH if lang() == "zh" else CLASS_NAMES)[investor_class]


def flag_label(flag: str) -> str:
    return (FLAG_LABELS_ZH if lang() == "zh" else FLAG_LABELS).get(flag, flag)


# Option keys shared by two questions that need different words.
OPTION_OVERRIDES = {("experience", "none"): ("Never", "从未投资过")}


def humanize(key: str, question: str | None = None) -> str:
    """Return a readable label for a questionnaire option key, falling back to the key."""

    if (question, key) in OPTION_OVERRIDES:
        return OPTION_OVERRIDES[(question, key)][1 if lang() == "zh" else 0]
    if lang() == "zh" and key in OPTION_LABELS_ZH:
        return OPTION_LABELS_ZH[key]
    return OPTION_LABELS.get(key, key.replace("_", " ").capitalize())


def question_label(key: str) -> str:
    if lang() == "zh" and key in QUESTION_LABELS_ZH:
        return QUESTION_LABELS_ZH[key]
    return QUESTION_LABELS.get(key, key.replace("_", " ").capitalize())


# Short noun labels for the "why this level" list, so each line reads "Label: answer".
REASON_LABELS = {
    "horizon": ("Time you can stay invested", "可投资时间"),
    "income_stability": ("Income", "收入"),
    "emergency_fund": ("Savings to live on", "存款可用时间"),
    "invested_share": ("Share of what you own", "占全部资产"),
    "liquidity_need": ("When you may need it back", "用钱时间"),
    "drawdown_reaction": ("If it fell 20%", "如果下跌20%"),
    "experience": ("Experience", "投资经验"),
    "goal": ("Goal", "目标"),
}


FIXED_REASONS = {
    "RISK_ADJUSTED_RETURN_NET_OF_FEES": ("Of similar funds, it gives the most return for its risk, after fees.", "在同类基金中，扣除费用后，承担同样风险收益最高。"),
    "REHEARSAL_HELD": ("You kept your investment through the 2008 crash test.", "在2008年危机演练中，您坚持持有。"),
    "REHEARSAL_SOLD_WITHIN_CLASS": ("You sold in the crash test, but at a loss your level already allows.", "您在危机演练中卖出，但亏损仍在您的风险等级允许范围内。"),
    "VULNERABILITY_CAP_APPLIED": ("A protection rule lowered your risk level (see the note above).", "保护规则降低了您的风险等级（见上方提示）。"),
    "LIQUIDITY_SLEEVE": ("You can take this money out quickly if you need it.", "需要时可以很快取出。"),
    "STRESS_LIMIT_APPLIED": ("We lowered the risk so a crash like the worst in history stays within the loss you said you can accept.", "我们降低了风险，让历史上最严重的下跌也不超过您能接受的亏损。"),
}


def risk_name(level: int) -> str:
    return (RISK_NAMES_ZH if lang() == "zh" else RISK_NAMES)[level]


def explain_reason(code: str) -> str:
    """Translate a deterministic reason code into one plain sentence in the current UI language."""

    zh = lang() == "zh"
    if match := re.fullmatch(r"SUITABLE_C(\d)_R(\d)", code):
        investor, product = (int(x) for x in match.groups())
        if zh:
            return f"这只基金是{risk_name(product)}，在您的风险等级（{class_name(investor)}）范围内。"
        return f"This fund is {risk_name(product)}, within your risk level ({class_name(investor)})."
    if match := re.fullmatch(r"REVEALED_TOLERANCE_C(\d)", code):
        level = class_name(int(match.group(1)))
        return f"您在危机演练中下跌时卖出，所以风险等级调整为{level}。" if zh else f"You sold during the fall in the crash test, so your risk level is now {level}."
    if code in FIXED_REASONS:
        return FIXED_REASONS[code][1 if zh else 0]
    for question in sorted(QUESTION_LABELS, key=len, reverse=True):
        prefix = question.upper() + "_"
        if code.startswith(prefix):
            answer = code[len(prefix):].lower()
            label = REASON_LABELS.get(question, (question_label(question),) * 2)[1 if zh else 0]
            return f"{label}{'：' if zh else ': '}{humanize(answer, question)}"
    return code.replace("_", " ").capitalize()
