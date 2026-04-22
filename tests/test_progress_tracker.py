from __future__ import annotations

from api.core.progress_tracker import AgentProgressTracker


def test_tracker_snapshot_contains_stage_and_agent():
    tracker = AgentProgressTracker(emit_events=False)

    tracker.mark_stage("running", "initializing")
    tracker._emit_token("Market Analyst", "market_report", "分析中")
    tracker.emit_debate_token("research", "Bull Researcher", 1, "多头观点")
    snapshot = tracker.snapshot()

    assert snapshot["current_agent"] == "Bull Researcher"
    assert snapshot["current_stage"] == "debating"
    assert snapshot["analysis_stage"] == "research_debate"
    assert snapshot["debate"]["name"] == "research"
    assert snapshot["debate"]["round"] == 1
    assert snapshot["has_streamed_content"] is True


def test_tracker_finalize_marks_completed_agent():
    tracker = AgentProgressTracker(emit_events=False)

    tracker._emit_token("Trader", "trader_investment_plan", "计划")
    tracker.finalize_report("Trader", "trader_investment_plan", "完整交易计划")
    snapshot = tracker.snapshot()

    assert snapshot["current_agent"] == "Trader"
    assert snapshot["current_stage"] == "section_finalized"
    assert snapshot["analysis_stage"] == "trade_planning"
    assert "Trader" in snapshot["completed_agents"]
