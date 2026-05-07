"""
风险管理经理 - P0优化
综合风险评估、仓位管理、止损止盈建议
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt
from tradingagents.agents.utils.agent_states import current_tracker_var


def create_risk_manager(llm, memory):
    """
    创建风险管理经理节点
    
    参数:
        llm: 语言模型实例
        memory: 记忆存储实例（用于获取历史风险管理经验）
    
    职责：
    1. 综合风险评估（市场风险、流动性风险、集中度风险）
    2. 仓位管理建议
    3. 止损止盈建议
    4. 风险等级评定
    """
    
    async def risk_manager_node(state) -> dict:
        # 获取输入数据
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]
        
        # 获取各分析师报告
        market_report = state.get("market_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")
        sentiment_report = state.get("sentiment_report", "")
        
        # 获取投资辩论结果
        investment_debate_state = state.get("investment_debate_state", {})
        bull_history = investment_debate_state.get("bull_history", "")
        bear_history = investment_debate_state.get("bear_history", "")
        investment_plan = state.get("investment_plan", "")
        trader_plan = state.get("trader_investment_plan", "")
        
        # 获取用户意图
        user_intent = state.get("user_intent") or {}
        user_context = user_intent.get("user_context", {})
        
        # ━━━ 计算量化风险指标 ━━━
        risk_metrics = await _calculate_risk_metrics(
            ticker=ticker,
            market_report=market_report,
            fundamentals_report=fundamentals_report,
            user_context=user_context,
        )
        
        # ━━━ 获取历史风险管理经验 ━━━
        curr_situation = f"{market_report}\n\n{fundamentals_report}\n\n{sentiment_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        
        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec.get("recommendation", "") + "\n\n"
        
        # ━━━ 生成综合风险报告 ━━━
        system_message = get_prompt("risk_manager_system_message", config=get_config())
        
        risk_prompt = f"""
【风险管理分析请求】

股票代码: {ticker}
分析日期: {current_date}

━━━ 历史风险管理经验 ━━━
{past_memory_str if past_memory_str else "无相关历史经验"}

━━━ 市场风险 ━━━
{risk_metrics.get('market_risk', '无数据')}

━━━ 基本面风险 ━━━
{risk_metrics.get('fundamental_risk', '无数据')}

━━━ 多空观点 ━━━
【多头观点】
{bull_history[:1000] if bull_history else "无"}

【空头观点】
{bear_history[:1000] if bear_history else "无"}

━━━ 研究总监方案 ━━━
{investment_plan[:1500] if investment_plan else "无"}

━━━ 交易员方案 ━━━
{trader_plan[:1500] if trader_plan else "无"}

━━━ 用户风险偏好 ━━━
风险偏好: {user_context.get('risk_profile', '未知')}
投资周期: {user_context.get('investment_horizon', '未知')}
最大承受损失: {user_context.get('max_loss_pct', '未知')}%

请基于以上信息，提供：
1. 综合风险评估（低/中/高/极高）
2. 对交易员方向的审核结论：原则上继承交易员方向；只有发现上游遗漏的重大风险时，才允许改方向，并必须明确说明遗漏点
3. 建议仓位比例（0-100%）
4. 止损价位和止盈价位
5. 主要风险点和应对策略
6. 最后一行必须写成：最终交易建议：买入 / 卖出 / 观望
7. 末尾追加机读摘要：<!-- VERDICT: {{"direction": "看多", "reason": "不超过20字的一句话核心结论"}} -->
direction 只可填：看多 / 偏多 / 中性 / 偏空 / 看空。若前置研究和交易员均偏空，不得输出看多/偏多/买入，除非正文明确给出足以翻转方向的新增证据。
"""
        
        messages = [
            SystemMessage(content=system_message + "\n\n请全程使用中文。"),
            HumanMessage(content=risk_prompt),
        ]
        
        # ━━ 流式输出 ━━
        tracker = current_tracker_var.get()
        full_content = ""
        async for chunk in llm.astream(messages):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            full_content += content
            if tracker:
                tracker._emit_token("Portfolio Manager", "final_trade_decision", content)
        if tracker:
            tracker.complete_agent("Portfolio Manager", analysis_stage="portfolio_decision")
        
        # ━━━ 提取决策 ━━━
        risk_level = _extract_risk_level(full_content)
        position_suggestion = _extract_position_suggestion(full_content)
        stop_loss, take_profit = _extract_stop_take_profit(full_content)
        
        return {
            "risk_report": full_content,
            "final_trade_decision": full_content,
            "risk_metrics": risk_metrics,
            "risk_level": risk_level,
            "position_suggestion": position_suggestion,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "analyst_traces": [{
                "agent": "risk_manager",
                "horizon": "综合",
                "key_finding": f"风险等级: {risk_level}",
                "verdict": position_suggestion,
            }],
        }
    
    return risk_manager_node


async def _calculate_risk_metrics(
    ticker: str,
    market_report: str,
    fundamentals_report: str,
    user_context: dict,
) -> Dict[str, Any]:
    """
    计算量化风险指标
    
    Returns:
        {
            "market_risk": {...},
            "fundamental_risk": {...},
            "overall_risk_score": 0.0-1.0,
        }
    """
    risk_metrics = {}
    
    # 1. 市场风险（基于技术指标）
    risk_metrics["market_risk"] = _analyze_market_risk(market_report)
    
    # 2. 基本面风险
    risk_metrics["fundamental_risk"] = _analyze_fundamental_risk(fundamentals_report)
    
    # 3. 综合风险评分
    market_score = risk_metrics["market_risk"].get("score", 0.5)
    fundamental_score = risk_metrics["fundamental_risk"].get("score", 0.5)
    
    risk_metrics["overall_risk_score"] = (market_score * 0.4 + fundamental_score * 0.6)
    
    return risk_metrics


def _analyze_market_risk(market_report: str) -> Dict[str, Any]:
    """
    分析市场风险
    
    基于技术报告中的关键词判断风险
    """
    risk_signals = {
        "high": ["下跌趋势", "跌破", "阻力位", "超买", "高位风险", "回调风险"],
        "medium": ["震荡", "盘整", "观望", "中性"],
        "low": ["上涨趋势", "支撑位", "突破", "超卖", "反弹"],
    }
    
    report_lower = market_report.lower()
    
    high_count = sum(1 for signal in risk_signals["high"] if signal in report_lower)
    low_count = sum(1 for signal in risk_signals["low"] if signal in report_lower)
    
    if high_count > low_count:
        return {
            "level": "高",
            "score": 0.7,
            "signals": [s for s in risk_signals["high"] if s in report_lower],
        }
    elif low_count > high_count:
        return {
            "level": "低",
            "score": 0.3,
            "signals": [s for s in risk_signals["low"] if s in report_lower],
        }
    else:
        return {
            "level": "中",
            "score": 0.5,
            "signals": [],
        }


def _analyze_fundamental_risk(fundamentals_report: str) -> Dict[str, Any]:
    """
    分析基本面风险
    """
    risk_signals = {
        "high": ["亏损", "负债率高", "现金流恶化", "业绩下滑", "风险提示"],
        "medium": ["持平", "稳定", "增长放缓"],
        "low": ["盈利", "现金流充裕", "业绩增长", "财务健康"],
    }
    
    report_lower = fundamentals_report.lower()
    
    high_count = sum(1 for signal in risk_signals["high"] if signal in report_lower)
    low_count = sum(1 for signal in risk_signals["low"] if signal in report_lower)
    
    if high_count > low_count:
        return {
            "level": "高",
            "score": 0.7,
            "signals": [s for s in risk_signals["high"] if s in report_lower],
        }
    elif low_count > high_count:
        return {
            "level": "低",
            "score": 0.3,
            "signals": [s for s in risk_signals["low"] if s in report_lower],
        }
    else:
        return {
            "level": "中",
            "score": 0.5,
            "signals": [],
        }


def _extract_risk_level(report: str) -> str:
    """从报告中提取风险等级"""
    if "极高" in report or "高风险" in report:
        return "极高"
    elif "高" in report or "较大风险" in report:
        return "高"
    elif "中" in report or "中等风险" in report:
        return "中"
    elif "低" in report or "风险可控" in report:
        return "低"
    else:
        return "中"


def _extract_position_suggestion(report: str) -> str:
    """从报告中提取仓位建议"""
    import re
    
    # 尝试提取百分比
    match = re.search(r'(\d{1,3})%', report)
    if match:
        return f"{match.group(1)}%"
    
    # 基于关键词判断
    if "轻仓" in report or "减仓" in report:
        return "20%-30%"
    elif "半仓" in report or "中性" in report:
        return "40%-60%"
    elif "重仓" in report or "加仓" in report:
        return "70%-90%"
    else:
        return "建议30%-50%"


def _extract_stop_take_profit(report: str) -> Tuple[Optional[str], Optional[str]]:
    """从报告中提取止损止盈价位"""
    import re
    
    stop_loss = None
    take_profit = None
    
    # 提取止损价位
    stop_match = re.search(r'止损[：:]\s*(\d+\.?\d*)', report)
    if stop_match:
        stop_loss = stop_match.group(1)
    
    # 提取止盈价位
    profit_match = re.search(r'止盈[：:]\s*(\d+\.?\d*)', report)
    if profit_match:
        take_profit = profit_match.group(1)
    
    return stop_loss, take_profit


# ━━━━ Prompt模板 ━━━━
RISK_MANAGER_SYSTEM_MESSAGE = """你是一位专业的风险管理经理，负责：

1. **综合风险评估**
   - 市场风险：技术面、流动性、波动率
   - 基本面风险：财务健康、盈利能力、负债水平
   - 行业风险：行业周期、政策风险、竞争格局

2. **仓位管理建议**
   - 根据风险等级建议仓位比例
   - 考虑用户风险偏好和投资周期
   - 提供分批建仓/减仓建议

3. **止损止盈策略**
   - 基于技术位设置止损价位
   - 根据风险收益比设置止盈目标
   - 提供移动止盈建议

4. **风险应对策略**
   - 识别主要风险点
   - 提供风险缓解措施
   - 制定应急预案

请以专业、客观的态度进行风险评估，输出格式化的风险报告。"""
