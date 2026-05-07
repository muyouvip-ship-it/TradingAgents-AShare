import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/tradingagents_test")

from api.routes.chat import _derive_direction, _resolve_deep_decision
from tradingagents.graph.signal_processing import _extract_decision_keyword


class _FallbackBuyGraph:
    def process_signal(self, _text: str) -> str:
        return "BUY"


def test_negated_buy_with_bearish_context_is_not_buy():
    text = "技术面偏空，资金流出。当前不建议买入，建议回避，等待企稳后再考虑买入机会。"

    assert _extract_decision_keyword(text) == "SELL"
    assert _derive_direction(text, "SELL", [{"verdict": "偏空"}, {"verdict": "看空"}]) == "偏空"


def test_negated_buy_without_sell_signal_is_hold():
    text = "当前不建议买入，等待放量确认后再评估。"

    assert _extract_decision_keyword(text) == "HOLD"


def test_kedaguochuang_like_bearish_chain_overrides_keyword_false_positive():
    traces = [
        {"agent": "market_analyst", "verdict": "偏空"},
        {"agent": "smart_money_analyst", "verdict": "偏空"},
        {"agent": "volume_price_analyst", "verdict": "看空"},
        {"agent": "risk_manager", "verdict": "85%"},
    ]
    final_risk = "科大国创风险偏高，技术面偏空，资金流出。当前不建议买入，建议回避，等待买入机会。"
    trader_plan = '最终交易建议：卖出\n<!-- VERDICT: {"direction": "偏空", "reason": "趋势和资金均偏弱"} -->'
    research_plan = '研究结论偏空\n<!-- VERDICT: {"direction": "偏空", "reason": "多维信号偏弱"} -->'

    decision = _resolve_deep_decision(
        graph=_FallbackBuyGraph(),
        final_trade_decision=final_risk,
        trader_investment_plan=trader_plan,
        investment_plan=research_plan,
        analyst_traces=traces,
    )

    assert decision == "SELL"
    assert _derive_direction(final_risk, decision, traces) == "偏空"
