from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

from api.main import app
from api.core.strategy_db import get_strategy_db_ctx
from api.models.strategy_models import RealtimeApprovalDB, RealtimeMonitorDB
from api.routes.strategy_platform import _default_dsl
from api.services import realtime_monitor_service
from api.services.qmt_virtual_account_service import QmtRuntimeConfig


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _auth(client: TestClient, email: str | None = None) -> str:
    target = email or f"realtime-{uuid4().hex[:8]}@test.com"
    response = client.post("/v1/auth/request-code", json={"email": target})
    code = response.json()["dev_code"]
    verified = client.post("/v1/auth/verify-code", json={"email": target, "code": code})
    return verified.json()["access_token"]


def _create_strategy(client: TestClient, name: str) -> str:
    response = client.post(
        "/v1/strategies",
        json={
            "name": name,
            "strategy_type": "trading",
            "description": "实时监控测试策略",
            "dsl": _default_dsl("trading").model_dump(),
            "status": "active",
            "source": "manual",
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def _mock_common(monkeypatch, account_key: str = "paper_sim", role: str = "paper"):
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key=account_key,
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628" if role == "paper" else "8886186680",
                account_type="STOCK",
                account_name="实时监控测试账户",
                userdata_path="D:/qmt/userdata_mini",
                role=role,
                bridge_base_url="http://127.0.0.1:8710" if role == "paper" else "http://127.0.0.1:8711",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.realtime_monitor_service.watchlist_service.list_watchlist",
        lambda db, user_id: [],
    )
    monkeypatch.setattr(
        "api.services.realtime_monitor_service.qmt_virtual_account_service.get_qmt_virtual_account_overview",
        lambda db, user_id, account_key=None: {
            "account": {
                "account_id": "39027628",
                "total_asset": 1_000_000.0,
                "available_cash": 900_000.0,
                "cash": 900_000.0,
            },
            "positions": [],
            "connection": {"account_key": account_key or "paper_sim"},
            "fetched_at": "2026-04-23T10:00:00+08:00",
        },
    )
    monkeypatch.setattr(
        "api.services.realtime_monitor_service.qmt_virtual_account_service._fetch_live_quotes",
        lambda symbols: {symbol: {"price": 10.5, "close": 10.4, "source": "mock"} for symbol in symbols},
    )
    monkeypatch.setattr(
        "api.services.realtime_monitor_service.evaluate_intraday_confirmation",
        lambda symbols, trade_date, timeframe="30m": type(
            "MinuteResult",
            (),
            {
                "timeframe": timeframe,
                "source": "mock",
                "items": [{"symbol": symbol, "confirmed": True, "timeframe": timeframe, "bar_end": datetime(2026, 4, 23, 10, 0, 0)} for symbol in symbols[:2]],
                "missing_symbols": [],
            },
        )(),
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service.submit_qmt_order",
        lambda db, user_id, **kwargs: {
            "message": "QMT 委托已提交",
            "account_key": kwargs.get("account_key"),
            "request_id": "mock-request-id",
            "order_result": {
                "success": True,
                "order_id": f"mock-{kwargs['symbol']}",
                "bridge": {"account_key": kwargs.get("account_key")},
            },
            "overview": {
                "orders": [
                    {
                        "order_id": f"mock-{kwargs['symbol']}",
                        "symbol": kwargs["symbol"],
                        "side": kwargs["side"],
                        "status": "submitted",
                        "quantity": kwargs["quantity"],
                    }
                ],
                "trades": [],
            },
        },
    )


def test_create_and_start_paper_monitor(monkeypatch):
    client = _client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    strategy_id = _create_strategy(client, f"实时测试策略-{uuid4().hex[:6]}")
    _mock_common(monkeypatch, account_key="paper_sim", role="paper")

    created = client.post(
        "/v1/realtime/monitors",
        headers=headers,
        json={
            "name": "虚拟仓自动监控",
            "strategy_id": strategy_id,
            "account_key": "paper_sim",
            "execution_mode": "auto",
            "monitor_pool": {"symbols": ["000001.SZ"]},
            "config": {"poll_interval_seconds": 10},
        },
    )
    assert created.status_code == 200
    monitor_id = created.json()["id"]
    assert created.json()["status"] == "ready"

    started = client.post(f"/v1/realtime/monitors/{monitor_id}/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    events = client.get(f"/v1/realtime/monitors/{monitor_id}/events", headers=headers)
    assert events.status_code == 200
    event_types = [item["event_type"] for item in events.json()["items"]]
    assert "monitor_created" in event_types
    assert "monitor_started" in event_types


def test_live_monitor_auto_trade_is_downgraded_to_monitor_only(monkeypatch):
    client = _client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    strategy_id = _create_strategy(client, f"实盘监控策略-{uuid4().hex[:6]}")
    _mock_common(monkeypatch, account_key="live_real", role="live")

    created = client.post(
        "/v1/realtime/monitors",
        headers=headers,
        json={
            "name": "实盘只读监控",
            "strategy_id": strategy_id,
            "account_key": "live_real",
            "execution_mode": "auto",
            "monitor_pool": {"symbols": ["600519.SH"]},
        },
    )
    assert created.status_code == 200
    monitor_id = created.json()["id"]

    started = client.post(f"/v1/realtime/monitors/{monitor_id}/start", headers=headers)
    assert started.status_code == 200
    payload = started.json()
    assert payload["status"] == "running"
    assert payload["execution_mode"] == "monitor_only"
    assert payload["auto_trade_enabled"] is False

    events = client.get(f"/v1/realtime/monitors/{monitor_id}/events", headers=headers)
    event_types = [item["event_type"] for item in events.json()["items"]]
    assert "live_readonly_guard" in event_types


def test_approval_queue_can_approve_and_reject(monkeypatch):
    client = _client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    strategy_id = _create_strategy(client, f"审批策略-{uuid4().hex[:6]}")
    _mock_common(monkeypatch, account_key="paper_sim", role="paper")

    created = client.post(
        "/v1/realtime/monitors",
        headers=headers,
        json={
            "name": "审批测试监控",
            "strategy_id": strategy_id,
            "account_key": "paper_sim",
            "execution_mode": "auto",
            "monitor_pool": {"symbols": ["000001.SZ"]},
        },
    )
    monitor = created.json()
    assert created.status_code == 200

    with get_strategy_db_ctx() as db:
        approval = RealtimeApprovalDB(
            id=uuid4().hex,
            monitor_id=monitor["id"],
            user_id=monitor["user_id"],
            account_key=monitor["account_key"],
            strategy_id=monitor["strategy_id"],
            symbol="000001.SZ",
            side="buy",
            status="pending",
            reason="同票多策略冲突",
            order_intent_json={
                "account_key": monitor["account_key"],
                "symbol": "000001.SZ",
                "side": "buy",
                "quantity": 100,
                "price_type": "opponent",
                "strategy_name": "RealtimeMonitor-Test",
                "order_remark": "approval-test",
            },
        )
        db.add(approval)
        db.commit()
        approval_id = approval.id

    queue = client.get("/v1/realtime/approvals", headers=headers)
    assert queue.status_code == 200
    assert any(item["id"] == approval_id for item in queue.json()["items"])

    approved = client.post(f"/v1/realtime/approvals/{approval_id}/approve", headers=headers, json={"decision": {"operator": "tester"}})
    assert approved.status_code == 200
    assert approved.json()["status"] in {"approved", "executed"}

    created_reject = client.post(
        "/v1/realtime/monitors",
        headers=headers,
        json={
            "name": "审批测试监控2",
            "strategy_id": strategy_id,
            "account_key": "paper_sim",
            "execution_mode": "auto",
            "monitor_pool": {"symbols": ["000002.SZ"]},
        },
    )
    monitor2 = created_reject.json()
    with get_strategy_db_ctx() as db:
        approval2 = RealtimeApprovalDB(
            id=uuid4().hex,
            monitor_id=monitor2["id"],
            user_id=monitor2["user_id"],
            account_key=monitor2["account_key"],
            strategy_id=monitor2["strategy_id"],
            symbol="000002.SZ",
            side="sell",
            status="pending",
            reason="人工拒绝测试",
            order_intent_json={"symbol": "000002.SZ", "side": "sell", "quantity": 100},
        )
        db.add(approval2)
        db.commit()
        approval2_id = approval2.id

    rejected = client.post(f"/v1/realtime/approvals/{approval2_id}/reject", headers=headers, json={"decision": {"operator": "tester"}})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_run_monitor_once_generates_signal_and_order_events(monkeypatch):
    client = _client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    strategy_id = _create_strategy(client, f"单轮执行策略-{uuid4().hex[:6]}")
    _mock_common(monkeypatch, account_key="paper_sim", role="paper")
    monkeypatch.setattr("api.services.realtime_monitor_service._is_trading_session", lambda value: True)

    created = client.post(
        "/v1/realtime/monitors",
        headers=headers,
        json={
            "name": "立即跑一轮测试",
            "strategy_id": strategy_id,
            "account_key": "paper_sim",
            "execution_mode": "auto",
            "monitor_pool": {"symbols": ["000001.SZ"]},
            "config": {"poll_interval_seconds": 20, "max_signals_per_cycle": 1},
        },
    )
    assert created.status_code == 200
    monitor_id = created.json()["id"]

    run_once = client.post(f"/v1/realtime/monitors/{monitor_id}/run-once", headers=headers)
    assert run_once.status_code == 200
    payload = run_once.json()
    assert payload["monitor"]["id"] == monitor_id
    event_types = [item["event_type"] for item in payload["events"]]
    assert "manual_cycle_requested" in event_types
    assert "cycle_started" in event_types
    assert "signal_generated" in event_types
    assert "order_submitted" in event_types


def test_run_monitor_once_replays_positions_and_auto_replaces_stale_order(monkeypatch):
    client = _client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    strategy_id = _create_strategy(client, f"撤单补单策略-{uuid4().hex[:6]}")
    _mock_common(monkeypatch, account_key="paper_sim", role="paper")
    monkeypatch.setattr("api.services.realtime_monitor_service._is_trading_session", lambda value: True)

    orders_state: dict[str, dict] = {}
    positions_state: list[dict] = []
    submit_count = {"value": 0}

    def overview(db, user_id, account_key=None):
        return {
            "account": {
                "account_id": "39027628",
                "total_asset": 1_000_000.0,
                "available_cash": 900_000.0,
                "cash": 900_000.0,
            },
            "positions": list(positions_state),
            "orders": list(orders_state.values()),
            "trades": [],
            "connection": {"account_key": account_key or "paper_sim"},
            "fetched_at": "2026-04-23T10:00:00+08:00",
        }

    def submit_order(db, user_id, **kwargs):
        submit_count["value"] += 1
        order_id = f"mock-{submit_count['value']}-{kwargs['symbol']}"
        orders_state[order_id] = {
            "order_id": order_id,
            "symbol": kwargs["symbol"],
            "side": kwargs["side"],
            "status": "submitted",
            "can_cancel": True,
            "quantity": kwargs["quantity"],
            "filled_quantity": 0,
            "price_type": kwargs.get("price_type"),
        }
        return {
            "message": "QMT 委托已提交",
            "account_key": kwargs.get("account_key"),
            "request_id": f"request-{submit_count['value']}",
            "order_result": {"success": True, "order_id": order_id},
            "overview": overview(db, user_id, account_key=kwargs.get("account_key")),
        }

    def cancel_order(db, user_id, *, account_key=None, order_id):
        orders_state[order_id] = {
            **orders_state[order_id],
            "status": "cancelled",
            "can_cancel": False,
        }
        return {
            "message": "QMT 撤单请求已提交",
            "account_key": account_key,
            "request_id": "cancel-request",
            "cancel_result": {"success": True, "order_id": order_id},
            "overview": overview(db, user_id, account_key=account_key),
        }

    monkeypatch.setattr(
        "api.services.realtime_monitor_service.qmt_virtual_account_service.get_qmt_virtual_account_overview",
        overview,
    )
    monkeypatch.setattr(
        "api.services.realtime_monitor_service.qmt_virtual_account_service.submit_qmt_order",
        submit_order,
    )
    monkeypatch.setattr(
        "api.services.realtime_monitor_service.qmt_virtual_account_service.cancel_qmt_order",
        cancel_order,
    )

    created = client.post(
        "/v1/realtime/monitors",
        headers=headers,
        json={
            "name": "撤单补单测试",
            "strategy_id": strategy_id,
            "account_key": "paper_sim",
            "execution_mode": "auto",
            "monitor_pool": {"symbols": ["000001.SZ"]},
            "config": {"poll_interval_seconds": 20, "max_signals_per_cycle": 1, "cancel_after_seconds": 1, "max_replace_attempts": 1},
        },
    )
    assert created.status_code == 200
    monitor_id = created.json()["id"]

    first_run = client.post(f"/v1/realtime/monitors/{monitor_id}/run-once", headers=headers)
    assert first_run.status_code == 200
    assert submit_count["value"] == 1

    with get_strategy_db_ctx() as db:
        monitor = db.query(RealtimeMonitorDB).filter(RealtimeMonitorDB.id == monitor_id).first()
        state = deepcopy(monitor.state_json or {})
        tracker = deepcopy(state.get("execution_tracker") or {})
        pending = deepcopy(tracker.get("pending_orders") or {})
        assert pending
        for item in pending.values():
            item["submitted_at"] = "2000-01-01T00:00:00+00:00"
        tracker["pending_orders"] = pending
        state["execution_tracker"] = tracker
        monitor.state_json = state
        flag_modified(monitor, "state_json")
        db.add(monitor)
        db.commit()

    positions_state.append(
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "current_position": 100,
            "available_position": 100,
            "market_value": 1050.0,
            "average_cost": 10.0,
        }
    )
    second_run = client.post(f"/v1/realtime/monitors/{monitor_id}/run-once", headers=headers)
    assert second_run.status_code == 200
    assert submit_count["value"] == 2

    event_types = [item["event_type"] for item in second_run.json()["events"]]
    assert "order_cancel_requested" in event_types
    assert "order_cancelled" in event_types
    assert "order_replace_requested" in event_types
    assert "position_changed" in event_types
    summary = second_run.json()["monitor"]["state"]["execution_tracker_summary"]
    assert summary["pending_orders"] == 1


def test_first_day_band_single_symbol_reentry_buy_uses_last_exit_quantity(monkeypatch):
    client = _client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    strategy_id = _create_strategy(client, f"首日波段回补策略-{uuid4().hex[:6]}")
    _mock_common(monkeypatch, account_key="paper_sim", role="paper")

    created = client.post(
        "/v1/realtime/monitors",
        headers=headers,
        json={
            "name": "首日波段单票回补",
            "strategy_id": strategy_id,
            "account_key": "paper_sim",
            "execution_mode": "auto",
            "monitor_pool": {"mode": "manual_only", "manual_symbols": ["300520.SZ"]},
            "config": {"signal_mode": "first_day_band", "signal_timeframe": "5m", "lot_size": 100},
        },
    )
    assert created.status_code == 200
    monitor_id = created.json()["id"]

    with get_strategy_db_ctx() as db:
        monitor = db.query(RealtimeMonitorDB).filter(RealtimeMonitorDB.id == monitor_id).first()
        realtime_monitor_service._sync_reentry_anchor_with_position_change(
            monitor,
            "300520.SZ",
            {"symbol": "300520.SZ", "current_position": 1000},
            None,
        )
        intent = realtime_monitor_service._build_order_intent(
            monitor,
            {
                "account": {
                    "total_asset": 1_000_000.0,
                    "available_cash": 900_000.0,
                    "cash": 900_000.0,
                },
                "positions": [],
            },
            {"symbol": "300520.SZ", "side": "buy", "price": 34.57, "target_position_pct": 0.2},
        )

    assert intent["quantity"] == 1000
    assert intent["reentry_anchor_quantity"] == 1000


def test_ensure_utc_interprets_naive_datetimes_as_local_time():
    naive_value = datetime(2026, 4, 27, 12, 57, 37)
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc

    converted = realtime_monitor_service._ensure_utc(naive_value)
    expected = naive_value.replace(tzinfo=local_tz).astimezone(timezone.utc)

    assert converted == expected


def test_monitor_due_handles_naive_local_heartbeat():
    local_now = datetime.now().astimezone().replace(tzinfo=None)
    monitor = RealtimeMonitorDB(
        id=uuid4().hex,
        user_id="tester",
        name="心跳时区测试",
        account_key="paper_sim",
        strategy_id=uuid4().hex,
        status="running",
        config_json={"poll_interval_seconds": 20},
        last_heartbeat_at=local_now - timedelta(seconds=45),
    )

    assert realtime_monitor_service._monitor_due(monitor) is True
