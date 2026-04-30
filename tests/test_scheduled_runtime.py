import asyncio

from api.main import _run_job
from api.schemas.analysis import AnalyzeRequest


def test_run_job_delegates_to_background_analysis(monkeypatch):
    captured = {}

    def fake_resolve_selected_analysts(requested, user_id):
        captured["requested"] = requested
        captured["user_id"] = user_id
        return ["market", "news"]

    async def fake_run_background_analysis_job(**kwargs):
        captured["job_kwargs"] = kwargs

    monkeypatch.setattr(
        "api.routes.chat._resolve_selected_analysts",
        fake_resolve_selected_analysts,
    )
    monkeypatch.setattr(
        "api.routes.chat._run_background_analysis_job",
        fake_run_background_analysis_job,
    )

    request = AnalyzeRequest(
        symbol="300750.SZ",
        trade_date="2026-04-30",
        query="定时分析 300750.SZ",
        selected_analysts=["macro"],
    )

    asyncio.run(_run_job("job-123", request, False, True, "user-1", "scheduled"))

    assert captured["requested"] == ["macro"]
    assert captured["user_id"] == "user-1"
    assert captured["job_kwargs"] == {
        "job_id": "job-123",
        "symbol": "300750.SZ",
        "trade_date": "2026-04-30",
        "query": "定时分析 300750.SZ",
        "user_id": "user-1",
        "selected_analysts": ["market", "news"],
    }
