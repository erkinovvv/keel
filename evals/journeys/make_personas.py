"""Generate 30 deterministic client personas with ground-truth questionnaire answers.

    uv run python evals/journeys/make_personas.py

Each persona's expected risk class comes from the production scoring code, so the journey eval
measures whether the agent elicits and records the client correctly, not whether it agrees with us.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from wealth_advisor.profiling import QUESTIONNAIRE, profile_investor

HERE = Path(__file__).parent

EN = {
    "horizon": {"under_1y": "I need the money within a year", "1_3y": "I can invest for one to three years", "3_7y": "I can leave it invested for about five years", "7_10y": "I can leave it for seven to ten years", "over_10y": "this is money for more than ten years"},
    "liquidity_need": {"within_1d": "I might need some of it any day", "within_7d": "I may need part of it within a week", "within_30d": "I may need part of it within a month", "over_30d": "I won't touch it for at least a month"},
    "income_stability": {"unstable": "my income is irregular", "mixed": "my income is partly stable", "stable": "I have a stable salary"},
    "emergency_fund": {"none": "I have no emergency savings", "3_6_months": "I keep three to six months of expenses in cash", "over_6_months": "I keep more than six months of expenses in cash"},
    "invested_share": {"over_75": "this is more than three quarters of everything I own", "50_75": "this is about two thirds of my savings", "25_50": "this is around a third of my savings", "under_25": "this is less than a quarter of my savings"},
    "drawdown_reaction": {"sell_all": "if it fell 20% I would sell everything", "reduce": "if it fell 20% I would sell some to limit losses", "hold": "if it fell 20% I would hold", "buy_more": "if it fell 20% I would buy more"},
    "experience": {"none": "I have never invested", "basic": "I only know deposits and a couple of funds", "good": "I have invested for several years", "advanced": "I trade actively and know the markets well"},
    "goal": {"preserve": "I mainly want to keep my capital safe", "income": "I want regular income", "growth": "I want long-term growth", "aggressive_growth": "I want maximum growth and accept high risk"},
}
ZH = {
    "horizon": {"under_1y": "一年内要用这笔钱", "1_3y": "可以投资一到三年", "3_7y": "大约可以投五年", "7_10y": "可以放七到十年", "over_10y": "这是十年以上的钱"},
    "liquidity_need": {"within_1d": "随时可能要取用", "within_7d": "一周内可能要用一部分", "within_30d": "一个月内可能要用一部分", "over_30d": "至少一个月不会动用"},
    "income_stability": {"unstable": "收入不稳定", "mixed": "收入比较稳定", "stable": "有稳定工资"},
    "emergency_fund": {"none": "没有应急存款", "3_6_months": "有三到六个月的应急资金", "over_6_months": "有六个月以上的应急资金"},
    "invested_share": {"over_75": "这是我四分之三以上的资产", "50_75": "这大约是我三分之二的积蓄", "25_50": "这大约是我三分之一的积蓄", "under_25": "这不到我积蓄的四分之一"},
    "drawdown_reaction": {"sell_all": "如果跌20%我会全部卖出", "reduce": "如果跌20%我会卖掉一部分", "hold": "如果跌20%我会继续持有", "buy_more": "如果跌20%我会加仓"},
    "experience": {"none": "我从来没投资过", "basic": "我只了解存款和少量基金", "good": "我投资了好几年", "advanced": "我是活跃的交易者"},
    "goal": {"preserve": "主要是保本", "income": "希望有稳定收益", "growth": "希望长期增值", "aggressive_growth": "追求最大收益，能接受高风险"},
}
NAMES = ["Aziz", "Mei", "Lucas", "Priya", "Jamal", "Sofia", "Kenji", "Amara", "Dilnoza", "Chen", "Elena", "Omar", "Hana", "Mateo", "Nilufar", "Wei", "Ines", "Rustam", "Yuki", "Zara"]


def build(seed: int = 7, count: int = 30) -> list[dict]:
    rng = random.Random(seed)
    personas = []
    for index in range(count):
        wanted = index % 5 + 1  # balanced: six personas per risk class C1-C5
        while True:
            answers = {key: rng.choice(list(spec["options"])) for key, spec in QUESTIONNAIRE.items()}
            age = rng.choice([22, 26, 31, 38, 45, 52, 61, 72])
            borrowed = rng.random() < 0.1
            if profile_investor(answers, age=age, borrowed_money=borrowed).investor_class == wanted:
                break
        lang = "zh" if index % 5 == 4 else "en"
        amount = rng.choice([20_000, 50_000, 100_000, 250_000, 600_000])
        horizon_years = {"under_1y": 1, "1_3y": 2, "3_7y": 5, "7_10y": 8, "over_10y": 15}[answers["horizon"]]
        max_loss = rng.choice([0.05, 0.1, 0.2, 0.3])
        expected = profile_investor(answers, age=age, borrowed_money=borrowed)
        phrases = ZH if lang == "zh" else EN
        facts = [phrases[key][value] for key, value in answers.items()]
        if lang == "zh":
            intro = f"你好，我{age}岁，想投资{amount:,}元，期限大约{horizon_years}年，一年最多能接受{int(max_loss * 100)}%的亏损。" + "；".join(facts) + ("。这笔钱有一部分是借来的。" if borrowed else "。")
        else:
            intro = f"Hi, I'm {age} and I have {amount:,} to invest for about {horizon_years} years; the most I could lose in a bad year is {int(max_loss * 100)}%. " + "; ".join(facts) + (". Part of this money is borrowed." if borrowed else ".")
        personas.append({
            "id": f"P{index + 1:02d}",
            "name": NAMES[index % len(NAMES)],
            "lang": lang,
            "age": age,
            "amount": amount,
            "horizon_years": horizon_years,
            "max_loss": max_loss,
            "borrowed_money": borrowed,
            "answers": answers,
            "expected_class": expected.investor_class,
            "turns": [intro, "请帮我做资产配置，并用2008年金融危机做压力测试。" if lang == "zh" else "Please build my portfolio and stress-test it against 2008."],
        })
    return personas


if __name__ == "__main__":
    personas = build()
    (HERE / "personas.json").write_text(json.dumps(personas, ensure_ascii=False, indent=1), encoding="utf-8")
    classes = sorted(p["expected_class"] for p in personas)
    print(f"wrote {len(personas)} personas; expected classes: {dict((c, classes.count(c)) for c in set(classes))}")
