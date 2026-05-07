# TradingAgents/graph/signal_processing.py

import re
import json

from langchain_openai import ChatOpenAI
from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt


class SignalProcessor:
    """Processes trading signals to extract actionable decisions."""

    def __init__(self, quick_thinking_llm: ChatOpenAI):
        """Initialize with an LLM for processing."""
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        """
        Process a full trading signal to extract the core decision.

        Args:
            full_signal: Complete trading signal text

        Returns:
            Extracted decision (BUY, SELL, or HOLD)
        """
        if not full_signal:
            return "HOLD"

        decision = _extract_decision_keyword(full_signal)
        if decision in {"BUY", "SELL", "HOLD"}:
            return decision

        messages = [
            (
                "system",
                get_prompt("signal_extractor_system", config=get_config()),
            ),
            ("human", full_signal),
        ]

        response = str(self.quick_thinking_llm.invoke(messages).content).strip().upper()
        if response in {"BUY", "SELL", "HOLD"}:
            return response
        return "HOLD"


def _extract_decision_keyword(text: str) -> str | None:
    """Rule-based decision extraction to keep UI consistent with final decision text."""
    raw = text or ""
    upper = raw.upper()

    def parse_verdict_direction(raw_text: str) -> str | None:
        match = re.search(r"<!--\s*VERDICT:\s*(\{.*?\})\s*-->", raw_text, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except Exception:
            return None
        direction = str(payload.get("direction", "")).strip().upper()
        direction_map = {
            "看多": "BUY",
            "偏多": "BUY",
            "BULLISH": "BUY",
            "BUY": "BUY",
            "看空": "SELL",
            "偏空": "SELL",
            "BEARISH": "SELL",
            "SELL": "SELL",
            "中性": "HOLD",
            "NEUTRAL": "HOLD",
            "HOLD": "HOLD",
            "谨慎": "HOLD",
            "CAUTIOUS": "HOLD",
        }
        return direction_map.get(direction)

    def classify(snippet: str, *, broad: bool = False) -> str | None:
        snippet = snippet.strip()
        snippet_upper = snippet.upper()
        if not snippet:
            return None

        sell_patterns = [
            r"\bSELL\b",
            r"卖出",
            r"减持",
            r"清仓",
            r"空仓",
            r"回避",
            r"看空",
            r"偏空",
            r"破位",
        ]
        buy_patterns = [
            r"\bBUY\b",
            r"买入",
            r"增持",
            r"做多",
            r"看多",
            r"偏多",
            r"有条件建仓",
            r"条件建仓",
            r"建仓",
        ]
        hold_patterns = [
            r"\bHOLD\b",
            r"观望",
            r"持有",
            r"中性",
            r"等待",
        ]
        negated_buy_patterns = [
            r"不(?:建议|宜|应|可|能)?\s*(?:追涨|买入|增持|建仓|做多)",
            r"暂(?:不|缓)\s*(?:买入|增持|建仓|做多)",
            r"(?:避免|禁止|切勿|不要|无需)\s*(?:追涨|买入|增持|建仓|做多)",
            r"不构成\s*(?:买入|增持|建仓|做多)",
            r"等待[^。\n；;]{0,12}(?:买入|建仓)机会",
        ]

        has_sell = any(re.search(pattern, snippet_upper, re.IGNORECASE) for pattern in sell_patterns)
        has_negated_buy = any(re.search(pattern, snippet, re.IGNORECASE) for pattern in negated_buy_patterns)
        has_buy = any(re.search(pattern, snippet_upper, re.IGNORECASE) for pattern in buy_patterns) and not has_negated_buy
        has_hold = any(re.search(pattern, snippet_upper, re.IGNORECASE) for pattern in hold_patterns)

        if has_sell:
            return "SELL"
        if has_buy:
            return "BUY"
        if has_hold or has_negated_buy:
            return "HOLD"
        if broad:
            return None
        return None

    verdict_decision = parse_verdict_direction(text)
    if verdict_decision:
        return verdict_decision

    explicit_patterns = [
        r"FINAL\s+TRANSACTION\s+PROPOSAL[:：]\s*\**\s*(BUY|SELL|HOLD)\s*\**",
        r"最终交易建议[:：]\s*([^\n*]+)",
        r"建议动作[:：]\s*([^\n*]+)",
        r"执行动作[:：]\s*([^\n*]+)",
        r"动作[:：]\s*([^\n*]+)",
        r"最终裁决[:：]\s*([^\n*]+)",
        r"风控委员会最终裁决[:：]\s*([^\n*]+)",
        r"最终建议[:：]\s*([^\n*]+)",
        r"方向[:：]\s*([^\n*]+)",
        r"核心定性[:：]\s*([^\n*]+)",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            decision = classify(match.group(1).strip())
            if decision:
                return decision

    headline = "\n".join(text.splitlines()[:20])
    decision = classify(headline)
    if decision:
        return decision

    decision = classify(raw, broad=True)
    if decision:
        return decision

    return None
