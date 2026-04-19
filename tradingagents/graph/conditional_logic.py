# TradingAgents/graph/conditional_logic.py

import re
import json
from typing import Tuple
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.debate_utils import safe_int


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(
        self,
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        consensus_threshold: float = 0.8,  # P1优化：共识度阈值
        min_debate_rounds: int = 1,  # P1优化：最小辩论轮次
    ):
        """Initialize with configuration parameters.
        
        Args:
            max_debate_rounds: 最大辩论轮次
            max_risk_discuss_rounds: 最大风险讨论轮次
            consensus_threshold: 共识度阈值（0-1），超过则提前结束
            min_debate_rounds: 最小辩论轮次（避免过早结束）
        """
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.consensus_threshold = consensus_threshold
        self.min_debate_rounds = min_debate_rounds

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "done"

    def should_continue_social(self, state: AgentState):
        """Determine if social media analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "done"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "done"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "done"

    def should_continue_macro(self, state: AgentState):
        """Determine if macro analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "done"

    def should_continue_smart_money(self, state: AgentState):
        """Determine if smart money analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "done"

    def should_continue_volume_price(self, state: AgentState):
        """Determine if volume price analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "done"

    def calculate_consensus(self, bull_history: str, bear_history: str) -> float:
        """
        计算多空共识度（P1优化：动态辩论机制）
        
        Returns:
            float: 0-1之间的共识度，1表示完全一致，0表示完全对立
        """
        # 提取关键观点
        bull_keywords = self._extract_keywords(bull_history)
        bear_keywords = self._extract_keywords(bear_history)
        
        # 计算关键词重叠度
        if not bull_keywords or not bear_keywords:
            return 0.5
        
        common_keywords = bull_keywords & bear_keywords
        total_keywords = bull_keywords | bear_keywords
        
        # 计算相似度
        similarity = len(common_keywords) / len(total_keywords) if total_keywords else 0
        
        # 检查观点一致性（通过情感分析简化版）
        bull_sentiment = self._analyze_sentiment(bull_history)
        bear_sentiment = self._analyze_sentiment(bear_history)
        
        # 情感接近度（如果多头和空头都认可某些点，说明有共识）
        sentiment_alignment = 1.0 - abs(bull_sentiment - bear_sentiment) / 2.0
        
        # 综合共识度
        consensus = similarity * 0.4 + sentiment_alignment * 0.6
        
        return consensus
    
    def _extract_keywords(self, text: str) -> set:
        """提取关键词"""
        # 金融关键词
        financial_keywords = [
            "上涨", "下跌", "看多", "看空", "买入", "卖出",
            "支撑位", "阻力位", "突破", "跌破",
            "盈利", "亏损", "增长", "下滑",
            "估值", "市盈率", "基本面", "技术面",
            "风险", "机会", "收益", "损失",
        ]
        
        found = set()
        text_lower = text.lower()
        for kw in financial_keywords:
            if kw in text_lower:
                found.add(kw)
        
        return found
    
    def _analyze_sentiment(self, text: str) -> float:
        """简单的情感分析（-1到1）"""
        positive_words = ["上涨", "看多", "买入", "盈利", "增长", "机会", "突破", "支撑"]
        negative_words = ["下跌", "看空", "卖出", "亏损", "下滑", "风险", "跌破", "阻力"]
        
        text_lower = text.lower()
        positive_count = sum(1 for w in positive_words if w in text_lower)
        negative_count = sum(1 for w in negative_words if w in text_lower)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0
        
        return (positive_count - negative_count) / total

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue.
        
        P1优化：基于共识度的动态辩论机制
        - 如果共识度超过阈值，提前结束
        - 如果已达最大轮次，强制结束
        - 否则继续辩论
        """
        debate_state = state["investment_debate_state"]
        current_round = debate_state.get("count", 0)
        max_rounds = 2 * self.max_debate_rounds  # 来回轮次
        
        # 检查是否达到最大轮次
        if current_round >= max_rounds:
            return "Research Manager"
        
        # 检查是否达到最小轮次（避免过早结束）
        if current_round < 2 * self.min_debate_rounds:
            # 继续辩论
            if debate_state.get("current_speaker", "").startswith("Bull"):
                return "Bear Researcher"
            return "Bull Researcher"
        
        # 计算共识度
        bull_history = debate_state.get("bull_history", "")
        bear_history = debate_state.get("bear_history", "")
        consensus = self.calculate_consensus(bull_history, bear_history)
        
        # 如果共识度超过阈值，提前结束
        if consensus >= self.consensus_threshold:
            print(f"[动态辩论] 共识度 {consensus:.2f} >= {self.consensus_threshold}，提前结束辩论")
            return "Research Manager"
        
        # 继续辩论
        print(f"[动态辩论] 共识度 {consensus:.2f} < {self.consensus_threshold}，继续辩论 (轮次 {current_round}/{max_rounds})")
        if debate_state.get("current_speaker", "").startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Risk Judge"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"

    def should_revise_after_risk_judge(self, state: AgentState) -> str:
        """Determine whether the trader must revise the plan after the risk judge."""
        feedback = state.get("risk_feedback_state", {})
        if (
            feedback.get("revision_required")
            and safe_int(feedback.get("retry_count", 0), 0) <= safe_int(feedback.get("max_retries", 1), 1)
        ):
            return "Trader"
        return "END"
