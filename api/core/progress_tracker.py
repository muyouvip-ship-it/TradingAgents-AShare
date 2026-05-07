from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict


class AgentProgressTracker:
    def __init__(
        self,
        emit_events: bool = True,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.emit_events = emit_events
        self.on_update = on_update
        self.status: Dict[str, str] = {}
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._started_reports: set[tuple[str, str]] = set()
        self._completed_reports: set[str] = set()
        self.has_streamed_content = False
        self.current_agent: str | None = None
        self.current_stage: str = "queued"
        self.analysis_stage: str = "queued"
        self.debate: dict[str, Any] = {
            "name": None,
            "agent": None,
            "round": None,
            "is_verdict": False,
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": dict(self.status),
            "current_agent": self.current_agent,
            "current_stage": self.current_stage,
            "analysis_stage": self.analysis_stage,
            "debate": dict(self.debate),
            "completed_agents": sorted(agent for agent, status in self.status.items() if status == "completed"),
            "has_streamed_content": self.has_streamed_content,
        }

    def _set_status(self, agent: str, status: str) -> None:
        self.status[agent] = status
        self.current_agent = agent
        if status == "in_progress":
            self.current_stage = "analyst_running"
            self.analysis_stage = "analyst_execution"
        elif status == "completed":
            self.current_stage = "agent_completed"
        self._notify()

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if not self.emit_events:
            return
        self._queue.put_nowait((event, data))

    async def next_event(self, timeout: float = 0.15) -> tuple[str, dict[str, Any]] | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def empty(self) -> bool:
        return self._queue.empty()

    def _emit_token(self, agent: str, report: str, token: str) -> None:
        if not token:
            return
        report_key = (agent, report)
        if self.status.get(agent) != "in_progress":
            self._set_status(agent, "in_progress")
            self._emit("agent.status", {"agent": agent, "status": "in_progress"})
        if report_key not in self._started_reports:
            self._started_reports.add(report_key)
        self.has_streamed_content = True
        self.current_agent = agent
        self.current_stage = "streaming_report"
        self.analysis_stage = self._infer_analysis_stage(report)
        self.debate = {"name": None, "agent": None, "round": None, "is_verdict": False}
        self._notify()
        self._emit("agent.token", {"agent": agent, "report": report, "token": token})

    def emit_debate_token(self, debate: str, agent: str, round_num: int, token: str) -> None:
        if not token:
            return
        if self.status.get(agent) != "in_progress":
            self._set_status(agent, "in_progress")
            self._emit("agent.status", {"agent": agent, "status": "in_progress"})
        self.has_streamed_content = True
        self.current_agent = agent
        self.current_stage = "debating"
        self.analysis_stage = "research_debate" if debate == "research" else "risk_debate"
        self.debate = {
            "name": debate,
            "agent": agent,
            "round": round_num,
            "is_verdict": False,
        }
        self._notify()
        self._emit(
            "agent.debate",
            {
                "debate": debate,
                "agent": agent,
                "round": round_num,
                "content": token,
                "is_verdict": False,
            },
        )

    def emit_debate_message(
        self,
        debate: str,
        agent: str,
        round_num: int,
        content: str,
        is_verdict: bool = False,
    ) -> None:
        if not content:
            self.complete_agent(agent, analysis_stage="research_debate" if debate == "research" else "risk_debate")
            return
        self.has_streamed_content = True
        self.current_agent = agent
        self.current_stage = "debate_verdict" if is_verdict else "debating"
        self.analysis_stage = "research_debate" if debate == "research" else "risk_debate"
        self.debate = {
            "name": debate,
            "agent": agent,
            "round": round_num,
            "is_verdict": is_verdict,
        }
        self._notify()
        self._emit(
            "agent.debate",
            {
                "debate": debate,
                "agent": agent,
                "round": round_num,
                "content": content,
                "is_verdict": is_verdict,
            },
        )
        self.complete_agent(agent, analysis_stage=self.analysis_stage)

    def finalize_report(self, agent: str, section: str, content: str) -> list[tuple[str, dict[str, Any]]]:
        if not content or section in self._completed_reports:
            return []
        report_key = (agent, section)
        events: list[tuple[str, dict[str, Any]]] = []
        if report_key not in self._started_reports:
            self._started_reports.add(report_key)
            self._set_status(agent, "in_progress")
            events.append(("agent.status", {"agent": agent, "status": "in_progress"}))
        events.append(("agent.report", {"section": section, "content": content}))
        self._set_status(agent, "completed")
        self.current_agent = agent
        self.current_stage = "section_finalized"
        self.analysis_stage = self._infer_analysis_stage(section)
        self.debate = {"name": None, "agent": None, "round": None, "is_verdict": False}
        self._notify()
        events.append(("agent.status", {"agent": agent, "status": "completed"}))
        self._completed_reports.add(section)
        return events

    def complete_agent(self, agent: str, analysis_stage: str | None = None) -> None:
        if not agent or self.status.get(agent) == "completed":
            return
        self.status[agent] = "completed"
        self.current_agent = agent
        self.current_stage = "agent_completed"
        if analysis_stage is not None:
            self.analysis_stage = analysis_stage
        self._notify()
        self._emit("agent.status", {"agent": agent, "status": "completed"})

    def mark_stage(self, current_stage: str, analysis_stage: str, current_agent: str | None = None) -> None:
        self.current_stage = current_stage
        self.analysis_stage = analysis_stage
        if current_agent is not None:
            self.current_agent = current_agent
        self._notify()

    def _notify(self) -> None:
        if self.on_update:
            self.on_update(self.snapshot())

    @staticmethod
    def _infer_analysis_stage(report: str) -> str:
        mapping = {
            "market_report": "market_analysis",
            "sentiment_report": "sentiment_analysis",
            "news_report": "news_analysis",
            "fundamentals_report": "fundamentals_analysis",
            "macro_report": "macro_analysis",
            "smart_money_report": "smart_money_analysis",
            "volume_price_report": "volume_price_analysis",
            "investment_plan": "research_synthesis",
            "investment_debate_state": "research_debate",
            "trader_investment_plan": "trade_planning",
            "risk_debate_state": "risk_debate",
            "final_trade_decision": "portfolio_decision",
        }
        return mapping.get(report, "analysis")
