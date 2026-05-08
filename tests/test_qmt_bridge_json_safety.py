import importlib.util
import json
import threading
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SCRIPTS = [
    ROOT / "scripts" / "qmt_bridge_server.py",
    ROOT / "windows_qmt_bridge_update" / "scripts" / "qmt_bridge_server.py",
]


def _load_bridge_module(path: Path):
    module_name = "qmt_bridge_server_" + "_".join(path.parts[-3:]).replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_qmt_bridge_json_safe_removes_non_finite_floats():
    for path in BRIDGE_SCRIPTS:
        module = _load_bridge_module(path)
        payload = {
            "nan": float("nan"),
            "inf": float("inf"),
            "nested": [{"neg_inf": float("-inf"), "ok": 1.23}],
        }

        safe_payload = module._json_safe(payload)

        assert safe_payload == {
            "nan": None,
            "inf": None,
            "nested": [{"neg_inf": None, "ok": 1.23}],
        }
        json.dumps(safe_payload, allow_nan=False)


def test_qmt_bridge_snapshot_payload_is_json_serializable(monkeypatch):
    class FakeTrader:
        def query_stock_asset(self, account):
            return SimpleNamespace(total_asset=float("nan"), available_cash=1000.0)

        def query_stock_positions(self, account):
            return [
                SimpleNamespace(
                    stockCode="000001",
                    stockName="平安银行",
                    enableAmount=float("inf"),
                    totalAmt=100,
                )
            ]

        def query_stock_orders(self, account):
            return [{"order_id": "O1", "symbol": "000001.SZ", "price": float("-inf")}]

        def query_stock_trades(self, account):
            return []

    for path in BRIDGE_SCRIPTS:
        module = _load_bridge_module(path)
        monkeypatch.setattr(
            module,
            "_create_trader",
            lambda account_id, account_type: (FakeTrader(), object(), threading.RLock(), "fake-cache"),
        )

        payload = module._query_snapshot("68042452", "STOCK")

        assert payload["asset"]["total_asset"] is None
        assert payload["positions"][0]["enableAmount"] is None
        assert payload["orders"][0]["price"] is None
        json.dumps(payload, allow_nan=False)
