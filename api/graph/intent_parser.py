from __future__ import annotations

from typing import Any, Dict, List


def parse_intent(text: str, llm, fallback_ticker: str = "") -> Dict[str, Any]:
    del llm
    return {"ticker": fallback_ticker or text.strip(), "horizons": ["short", "medium"], "focus_areas": [], "specific_questions": []}


def build_horizon_context(horizon: str, focus_areas: List[str], specific_questions: List[str], agent_type: str = "") -> str:
    return "次要" if agent_type == "fundamentals" and horizon == "short" else "【分析视角】\n当前分析维度：短线（1-2周，技术面主导）\n用户重点关注：无特殊关注\n具体问题：无\n\n请基于以上视角调整分析重点。"
