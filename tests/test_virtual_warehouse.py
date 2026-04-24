from fastapi.testclient import TestClient
from types import SimpleNamespace
from uuid import uuid4

from api.database import ImportedPortfolioPositionDB, QmtAccountSnapshotDB, get_db_ctx
from api.data_downloader import DataDownloader
from api.services.qmt_virtual_account_service import QmtRuntimeConfig


def _get_client():
    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _auth(client: TestClient) -> str:
    response = client.post("/v1/auth/request-code", json={"email": "virtual-warehouse@test.com"})
    code = response.json()["dev_code"]
    verified = client.post("/v1/auth/verify-code", json={"email": "virtual-warehouse@test.com", "code": code})
    return verified.json()["access_token"]


def test_qmt_virtual_warehouse_overview(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_demo",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="demo123",
                account_type="STOCK",
                account_name="QMT 模拟测试账户",
                userdata_path="C:/miniqmt/userdata_mini",
                role="paper",
                bridge_base_url="",
                bridge_token="",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._query_qmt_snapshot",
        lambda config: {
            "fund": {"assetBalance": 1250000.0, "marketValue": 850000.0, "enableBalance": 400000.0},
            "positions": [
                {
                    "stockCode": "600519",
                    "stockName": "贵州茅台",
                    "totalAmt": 100,
                    "enableAmount": 100,
                    "costPrice": 1680.0,
                    "lastPrice": 1715.0,
                    "marketValue": 171500.0,
                    "income": 3500.0,
                }
            ],
            "asset": {"cash": 400000.0},
        },
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._fetch_live_quotes",
        lambda symbols: {
            "600519.SH": {
                "price": 1715.0,
                "previous_close": 1702.0,
                "change": 13.0,
                "change_pct": 0.7638,
                "quote_time": "2026-04-22 14:58:00",
                "source": "mock",
            }
        },
    )

    response = client.get("/v1/virtual-warehouse/qmt/overview", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["connection"]["connected"] is True
    assert payload["active_account_key"] == "paper_demo"
    assert payload["accounts"][0]["account_key"] == "paper_demo"
    assert payload["account"]["account_id"] == "demo123"
    assert payload["summary"]["position_count"] == 1
    assert payload["positions"][0]["symbol"] == "600519.SH"
    assert payload["positions"][0]["today_pnl"] == 1300.0
    assert payload["last_synced_at"] is not None
    assert payload["data_source"] == "live"

    with get_db_ctx() as db:
        row = (
            db.query(QmtAccountSnapshotDB)
            .filter(
                QmtAccountSnapshotDB.account_key == "paper_demo",
            )
            .first()
        )
        assert row is not None
        assert row.positions_json


def test_qmt_virtual_warehouse_sync_does_not_write_tracking_board(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/v1/auth/me", headers=headers).json()

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_demo",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="demo123",
                account_type="STOCK",
                account_name="QMT 模拟测试账户",
                userdata_path="C:/miniqmt/userdata_mini",
                role="paper",
                bridge_base_url="",
                bridge_token="",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._query_qmt_snapshot",
        lambda config: {
            "fund": {"assetBalance": 1000000.0, "marketValue": 100000.0, "enableBalance": 900000.0},
            "positions": [
                {
                    "stockCode": "300750",
                    "stockName": "宁德时代",
                    "totalAmt": 200,
                    "enableAmount": 100,
                    "costPrice": 200.0,
                    "lastPrice": 210.0,
                    "marketValue": 42000.0,
                    "income": 2000.0,
                }
            ],
            "asset": {"cash": 900000.0},
        },
    )
    monkeypatch.setattr("api.services.qmt_virtual_account_service._fetch_live_quotes", lambda symbols: {})

    response = client.post("/v1/virtual-warehouse/qmt/sync", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] is None
    assert "隔离" in payload["message"]

    with get_db_ctx() as db:
        row = (
            db.query(ImportedPortfolioPositionDB)
            .filter(
                ImportedPortfolioPositionDB.user_id == me["id"],
                ImportedPortfolioPositionDB.symbol == "300750.SZ",
            )
            .first()
        )
        assert row is None


def test_qmt_virtual_warehouse_diagnostics(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_sim",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628",
                account_type="STOCK",
                account_name="国金QMT模拟仓",
                userdata_path="D:/国金QMT交易端模拟/userdata_mini",
                role="paper",
                bridge_base_url="",
                bridge_token="",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._check_xtquant_available",
        lambda: (True, "xtquant 已安装"),
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service.os.path.exists",
        lambda path: True,
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._run_connect_diagnostic",
        lambda config: {"attempted": True, "connected": True, "message": "连接成功，可读取账户资产与持仓"},
    )

    response = client.get("/v1/virtual-warehouse/qmt/diagnostics?run_connect_test=true", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["connected"] == 1
    assert payload["items"][0]["account_key"] == "paper_sim"
    assert payload["items"][0]["ready"] is True


def test_qmt_virtual_warehouse_overview_via_bridge(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_bridge",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628",
                account_type="STOCK",
                account_name="QMT Bridge 模拟仓",
                userdata_path="",
                role="paper",
                bridge_base_url="http://127.0.0.1:8710",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._query_qmt_snapshot_via_bridge",
        lambda config: {
            "fund": {"assetBalance": 800000.0, "marketValue": 300000.0, "enableBalance": 500000.0},
            "positions": [
                {
                    "stockCode": "000001",
                    "stockName": "平安银行",
                    "totalAmt": 1000,
                    "enableAmount": 1000,
                    "costPrice": 12.0,
                    "lastPrice": 12.5,
                    "marketValue": 12500.0,
                    "income": 500.0,
                }
            ],
            "orders": [
                {
                    "orderId": "O001",
                    "stockCode": "000001",
                    "stockName": "平安银行",
                    "orderType": "buy",
                    "orderStatus": "filled",
                    "orderPrice": 12.4,
                    "orderVolume": 1000,
                    "tradedVolume": 1000,
                    "orderTime": "2026-04-22 10:00:00",
                }
            ],
            "trades": [
                {
                    "tradedId": "T001",
                    "orderId": "O001",
                    "stockCode": "000001",
                    "stockName": "平安银行",
                    "orderType": "buy",
                    "tradedPrice": 12.4,
                    "tradedVolume": 1000,
                    "tradedTime": "2026-04-22 10:00:03",
                }
            ],
            "asset": {"cash": 500000.0},
            "bridge": {"mode": "http_bridge"},
        },
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._fetch_live_quotes",
        lambda symbols: {"000001.SZ": {"price": 12.5, "previous_close": 12.3, "change": 0.2, "change_pct": 1.626}},
    )

    response = client.get("/v1/virtual-warehouse/qmt/overview?account_key=paper_bridge", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["connection"]["connected"] is True
    assert payload["positions"][0]["symbol"] == "000001.SZ"
    assert payload["orders"][0]["order_id"] == "O001"
    assert payload["trades"][0]["trade_id"] == "T001"
    assert payload["account"]["total_asset"] == 800000.0


def test_qmt_virtual_warehouse_name_fallback_from_cached_map(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_bridge",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628",
                account_type="STOCK",
                account_name="QMT Bridge 模拟仓",
                userdata_path="",
                role="paper",
                bridge_base_url="http://127.0.0.1:8710",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._query_qmt_snapshot_via_bridge",
        lambda config: {
            "fund": {"assetBalance": 800000.0, "marketValue": 300000.0, "enableBalance": 500000.0},
            "positions": [
                {
                    "stockCode": "600006",
                    "totalAmt": 100,
                    "enableAmount": 100,
                    "costPrice": 6.2,
                    "lastPrice": 6.42,
                    "marketValue": 642.0,
                    "income": 22.0,
                }
            ],
            "orders": [],
            "trades": [],
            "asset": {"cash": 500000.0},
            "bridge": {"mode": "http_bridge"},
        },
    )
    monkeypatch.setattr("api.services.qmt_virtual_account_service._fetch_live_quotes", lambda symbols: {})
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service.get_reverse_stock_map_cached_only",
        lambda: {"600006.SH": "东风股份"},
    )

    response = client.get("/v1/virtual-warehouse/qmt/overview?account_key=paper_bridge", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["positions"][0]["symbol"] == "600006.SH"
    assert payload["positions"][0]["name"] == "东风股份"


def test_qmt_overview_only_fetches_active_account(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_sim",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628",
                account_type="STOCK",
                account_name="QMT 模拟仓",
                userdata_path="",
                role="paper",
                bridge_base_url="http://127.0.0.1:8710",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            ),
            QmtRuntimeConfig(
                key="live_real",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="8886186680",
                account_type="STOCK",
                account_name="QMT 实盘仓",
                userdata_path="",
                role="live",
                bridge_base_url="http://127.0.0.1:8711",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            ),
        ],
    )

    fetched: list[str] = []

    def fake_query(config):
        fetched.append(config.key)
        return {
            "fund": {"assetBalance": 1000.0, "marketValue": 0.0, "enableBalance": 1000.0},
            "positions": [],
            "orders": [],
            "trades": [],
            "asset": {"cash": 1000.0},
        }

    monkeypatch.setattr("api.services.qmt_virtual_account_service._query_qmt_snapshot", fake_query)
    monkeypatch.setattr("api.services.qmt_virtual_account_service._fetch_live_quotes", lambda symbols: {})

    response = client.get("/v1/virtual-warehouse/qmt/overview?account_key=live_real", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_account_key"] == "live_real"
    assert fetched == ["live_real"]
    assert payload["accounts"][0]["summary"]["total_asset"] == 0.0
    assert payload["accounts"][1]["summary"]["total_asset"] == 1000.0


def test_qmt_overview_falls_back_to_cached_snapshot(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_sim",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628",
                account_type="STOCK",
                account_name="QMT 模拟仓",
                userdata_path="",
                role="paper",
                bridge_base_url="http://127.0.0.1:8710",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            ),
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._query_qmt_snapshot_via_bridge",
        lambda config: {
            "fund": {"assetBalance": 100000.0, "marketValue": 20000.0, "enableBalance": 80000.0},
            "positions": [
                {
                    "stockCode": "000001",
                    "stockName": "平安银行",
                    "totalAmt": 1000,
                    "enableAmount": 1000,
                    "costPrice": 12.0,
                    "lastPrice": 12.5,
                    "marketValue": 12500.0,
                    "income": 500.0,
                }
            ],
            "orders": [],
            "trades": [],
            "asset": {"cash": 80000.0},
        },
    )
    monkeypatch.setattr("api.services.qmt_virtual_account_service._fetch_live_quotes", lambda symbols: {})

    first_response = client.get("/v1/virtual-warehouse/qmt/overview?account_key=paper_sim", headers=headers)
    assert first_response.status_code == 200
    first_payload = first_response.json()
    assert first_payload["data_source"] == "live"
    assert first_payload["positions"][0]["name"] == "平安银行"

    def fail_query(config):
        raise RuntimeError("bridge disconnected")

    monkeypatch.setattr("api.services.qmt_virtual_account_service._query_qmt_snapshot_via_bridge", fail_query)

    second_response = client.get("/v1/virtual-warehouse/qmt/overview?account_key=paper_sim", headers=headers)
    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload["data_source"] == "cache"
    assert second_payload["is_stale"] is True
    assert second_payload["positions"][0]["name"] == "平安银行"
    assert "最近快照" in second_payload["connection"]["message"]


def test_qmt_sync_profile_endpoint():
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/v1/virtual-warehouse/qmt/sync-profiles/paper_sim",
        headers=headers,
        json={
            "is_active": True,
            "sync_interval_seconds": 45,
            "sync_tracking_board": True,
            "alert_on_disconnect": True,
        },
    )
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["account_key"] == "paper_sim"
    assert payload["is_active"] is True
    assert payload["sync_interval_seconds"] == 45
    assert payload["sync_tracking_board"] is False

    list_response = client.get("/v1/virtual-warehouse/qmt/sync-profiles", headers=headers)
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert any(item["account_key"] == "paper_sim" for item in items)


def test_qmt_submit_order_route(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_bridge",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628",
                account_type="STOCK",
                account_name="QMT Bridge 模拟仓",
                userdata_path="",
                role="paper",
                bridge_base_url="http://127.0.0.1:8710",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._submit_qmt_order",
        lambda config, **kwargs: {
            "success": True,
            "order_id": "O9001",
            "result": "O9001",
            "request": kwargs,
        },
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._query_qmt_snapshot",
        lambda config: {
            "fund": {"assetBalance": 800000.0, "marketValue": 300000.0, "enableBalance": 500000.0},
            "positions": [],
            "orders": [
                {
                    "orderId": "O9001",
                    "stockCode": "000001",
                    "stockName": "平安银行",
                    "orderType": "buy",
                    "orderStatus": "submitted",
                    "orderPrice": 12.4,
                    "orderVolume": 1000,
                    "tradedVolume": 0,
                    "orderTime": "2026-04-22 10:00:00",
                }
            ],
            "trades": [],
            "asset": {"cash": 500000.0},
        },
    )
    monkeypatch.setattr("api.services.qmt_virtual_account_service._fetch_live_quotes", lambda symbols: {})

    response = client.post(
        "/v1/virtual-warehouse/qmt/orders",
        headers=headers,
        json={
            "account_key": "paper_bridge",
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 1000,
            "price": 12.4,
            "price_type": "limit",
            "strategy_name": "test",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["order_result"]["order_id"] == "O9001"
    assert payload["overview"]["orders"][0]["order_id"] == "O9001"


def test_qmt_submit_order_rejects_live_account(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    called = {"submit": False}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="live_real",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="8886186680",
                account_type="STOCK",
                account_name="QMT 实盘仓",
                userdata_path="",
                role="live",
                bridge_base_url="http://127.0.0.1:8711",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            )
        ],
    )

    def fake_submit(*args, **kwargs):
        called["submit"] = True
        return {"success": True}

    monkeypatch.setattr("api.services.qmt_virtual_account_service._submit_qmt_order", fake_submit)
    response = client.post(
        "/v1/virtual-warehouse/qmt/orders",
        headers=headers,
        json={
            "account_key": "live_real",
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 12.4,
            "price_type": "limit",
        },
    )
    assert response.status_code == 400
    assert "实盘仓已启用只读锁定" in response.json()["detail"]
    assert called["submit"] is False


def test_qmt_cancel_order_route(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="paper_bridge",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="39027628",
                account_type="STOCK",
                account_name="QMT Bridge 模拟仓",
                userdata_path="",
                role="paper",
                bridge_base_url="http://127.0.0.1:8710",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            )
        ],
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._cancel_qmt_order",
        lambda config, **kwargs: {
            "success": True,
            "order_id": kwargs["order_id"],
            "result": 0,
        },
    )
    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._query_qmt_snapshot",
        lambda config: {
            "fund": {"assetBalance": 800000.0, "marketValue": 300000.0, "enableBalance": 500000.0},
            "positions": [],
            "orders": [
                {
                    "orderId": "O9001",
                    "stockCode": "000001",
                    "stockName": "平安银行",
                    "orderType": "buy",
                    "orderStatus": "cancelled",
                    "orderPrice": 12.4,
                    "orderVolume": 1000,
                    "tradedVolume": 0,
                    "orderTime": "2026-04-22 10:00:00",
                }
            ],
            "trades": [],
            "asset": {"cash": 500000.0},
        },
    )
    monkeypatch.setattr("api.services.qmt_virtual_account_service._fetch_live_quotes", lambda symbols: {})

    response = client.post(
        "/v1/virtual-warehouse/qmt/orders/O9001/cancel?account_key=paper_bridge",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["cancel_result"]["order_id"] == "O9001"
    assert payload["overview"]["orders"][0]["status"] == "cancelled"


def test_qmt_cancel_order_rejects_live_account(monkeypatch):
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    called = {"cancel": False}

    monkeypatch.setattr(
        "api.services.qmt_virtual_account_service._runtime_configs",
        lambda: [
            QmtRuntimeConfig(
                key="live_real",
                enabled=True,
                host="192.168.10.1",
                port=58610,
                account_id="8886186680",
                account_type="STOCK",
                account_name="QMT 实盘仓",
                userdata_path="",
                role="live",
                bridge_base_url="http://127.0.0.1:8711",
                bridge_token="bridge-token",
                refresh_interval_seconds=10,
            )
        ],
    )

    def fake_cancel(*args, **kwargs):
        called["cancel"] = True
        return {"success": True}

    monkeypatch.setattr("api.services.qmt_virtual_account_service._cancel_qmt_order", fake_cancel)
    response = client.post(
        "/v1/virtual-warehouse/qmt/orders/O9001/cancel?account_key=live_real",
        headers=headers,
    )
    assert response.status_code == 400
    assert "实盘仓已启用只读锁定" in response.json()["detail"]
    assert called["cancel"] is False


def test_qmt_history_bridge_uses_paper_account_key(monkeypatch):
    monkeypatch.delenv("QMT_HISTORY_BRIDGE_BASE_URL", raising=False)
    monkeypatch.setenv("QMT_HISTORY_ACCOUNT_KEY", "paper_sim")
    fake_settings = SimpleNamespace(
        qmt_history_account_key="paper_sim",
        qmt_accounts=lambda: [
            {
                "key": "live_real",
                "enabled": True,
                "role": "live",
                "account_id": "8886186680",
                "bridge_base_url": "http://192.168.10.1:8711",
                "bridge_token": "live-token",
            },
            {
                "key": "paper_sim",
                "enabled": True,
                "role": "paper",
                "account_id": "39027628",
                "bridge_base_url": "http://192.168.10.1:8710",
                "bridge_token": "paper-token",
            },
        ],
        qmt_accounts_json="[]",
        qmt_default_account_key="paper_sim",
        qmt_bridge_base_url="",
        qmt_bridge_token="",
        qmt_account_id="",
    )
    monkeypatch.setattr("api.data_downloader.settings", fake_settings)

    bridge = DataDownloader._resolve_qmt_history_bridge()

    assert bridge is not None
    assert bridge["account_key"] == "paper_sim"
    assert bridge["role"] == "paper"
    assert bridge["bridge_base_url"].endswith(":8710")


def test_qmt_history_bridge_rejects_live_history_key(monkeypatch):
    monkeypatch.delenv("QMT_HISTORY_BRIDGE_BASE_URL", raising=False)
    monkeypatch.setenv("QMT_HISTORY_ACCOUNT_KEY", "live_real")
    fake_settings = SimpleNamespace(
        qmt_history_account_key="paper_sim",
        qmt_accounts=lambda: [
            {
                "key": "live_real",
                "enabled": True,
                "role": "live",
                "account_id": "8886186680",
                "bridge_base_url": "http://192.168.10.1:8711",
                "bridge_token": "live-token",
            }
        ],
        qmt_accounts_json="[]",
        qmt_default_account_key="paper_sim",
        qmt_bridge_base_url="",
        qmt_bridge_token="",
        qmt_account_id="",
    )
    monkeypatch.setattr("api.data_downloader.settings", fake_settings)

    assert DataDownloader._resolve_qmt_history_bridge() is None


def test_qmt_history_bridge_rejects_explicit_live_port(monkeypatch):
    monkeypatch.setenv("QMT_HISTORY_BRIDGE_BASE_URL", "http://192.168.10.1:8711")
    monkeypatch.setenv("QMT_HISTORY_ACCOUNT_KEY", "paper_sim")

    assert DataDownloader._resolve_qmt_history_bridge() is None


def test_list_paper_accounts_endpoint():
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    account_id = f"paper-list-{uuid4().hex[:8]}"
    create_response = client.post(
        "/v1/paper/accounts",
        headers=headers,
        json={"id": account_id, "name": "纸交易列表测试账户", "initial_capital": 500000},
    )
    assert create_response.status_code == 200

    list_response = client.get("/v1/paper/accounts", headers=headers)
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert any(item["id"] == account_id for item in items)
