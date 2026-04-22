from __future__ import annotations

import logging
import math
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests
from sqlalchemy.orm import Session

from api.core.stock_map import get_reverse_stock_map_cached_only
from api.core.settings import settings
from api.database import ImportedPortfolioPositionDB, QmtAccountSnapshotDB, VirtualPositionStateDB
from api.services import portfolio_import_service
from tradingagents.dataflows.interface import route_to_vendor


logger = logging.getLogger(__name__)
SOURCE_NAME = "qmt_virtual"


@dataclass(frozen=True)
class QmtRuntimeConfig:
    key: str
    enabled: bool
    host: str
    port: int
    account_id: str
    account_type: str
    account_name: str
    userdata_path: str
    role: str
    bridge_base_url: str
    bridge_token: str
    refresh_interval_seconds: int


def get_qmt_virtual_account_overview(
    db: Session,
    user_id: str,
    *,
    account_key: str | None = None,
    sync_to_imports: bool = False,
) -> dict[str, Any]:
    configs = _runtime_configs()
    account_summaries: list[dict[str, Any]] = []
    active_payload: dict[str, Any] | None = None
    active_key = _resolve_active_key(configs, account_key)

    for config in configs:
        is_active = config.key == active_key
        payload = (
            _load_account_payload(db, user_id, config, sync_to_imports=sync_to_imports and is_active)
            if is_active
            else _load_empty_payload(config)
        )
        account_summaries.append({
            "account_key": config.key,
            "role": config.role,
            "connection": payload["connection"],
            "account": payload["account"],
            "summary": payload["summary"],
            "refresh_interval_seconds": payload["refresh_interval_seconds"],
            "last_synced_at": payload.get("last_synced_at"),
            "data_source": payload.get("data_source"),
            "is_stale": bool(payload.get("is_stale", False)),
        })
        if is_active:
            active_payload = payload

    if active_payload is None:
        active_payload = _load_empty_payload(_pick_active_config(configs, active_key))

    return {
        **active_payload,
        "active_account_key": active_payload["connection"].get("account_key"),
        "accounts": account_summaries,
    }


def sync_qmt_virtual_positions(db: Session, user_id: str, account_key: str | None = None) -> dict[str, Any]:
    overview = get_qmt_virtual_account_overview(db, user_id, account_key=account_key, sync_to_imports=False)
    summary = overview.get("summary") or {}
    return {
        "message": "QMT 仓位与跟踪看板已隔离，当前版本不再执行同步写入",
        "source": None,
        "summary": {
            "positions": summary.get("position_count", 0),
            "market_value": summary.get("market_value", 0.0),
            "total_asset": summary.get("total_asset", 0.0),
        },
        "overview": overview,
    }


def list_qmt_orders(db: Session, user_id: str, *, account_key: str | None = None) -> dict[str, Any]:
    overview = get_qmt_virtual_account_overview(db, user_id, account_key=account_key)
    return {
        "active_account_key": overview.get("active_account_key"),
        "items": overview.get("orders") or [],
        "connection": overview.get("connection") or {},
        "fetched_at": overview.get("fetched_at"),
    }


def list_qmt_trades(db: Session, user_id: str, *, account_key: str | None = None) -> dict[str, Any]:
    overview = get_qmt_virtual_account_overview(db, user_id, account_key=account_key)
    return {
        "active_account_key": overview.get("active_account_key"),
        "items": overview.get("trades") or [],
        "connection": overview.get("connection") or {},
        "fetched_at": overview.get("fetched_at"),
    }


def submit_qmt_order(
    db: Session,
    user_id: str,
    *,
    account_key: str | None,
    symbol: str,
    side: str,
    quantity: int,
    price: float | None,
    price_type: str,
    strategy_name: str | None = None,
    order_remark: str | None = None,
) -> dict[str, Any]:
    config = _resolve_runtime_config(account_key)
    if not config.enabled:
        raise RuntimeError("当前 QMT 账户未启用")
    if quantity <= 0:
        raise RuntimeError("委托数量必须大于 0")
    if str(price_type or "limit").strip().lower() == "limit" and price in (None, 0):
        raise RuntimeError("限价委托必须填写价格")

    result = _submit_qmt_order(
        config,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        price_type=price_type,
        strategy_name=strategy_name,
        order_remark=order_remark,
    )
    overview = get_qmt_virtual_account_overview(db, user_id, account_key=config.key)
    return {
        "message": "QMT 委托已提交",
        "account_key": config.key,
        "order_result": result,
        "overview": overview,
    }


def cancel_qmt_order(
    db: Session,
    user_id: str,
    *,
    account_key: str | None,
    order_id: str,
) -> dict[str, Any]:
    config = _resolve_runtime_config(account_key)
    if not config.enabled:
        raise RuntimeError("当前 QMT 账户未启用")
    if not str(order_id or "").strip():
        raise RuntimeError("缺少 order_id")

    result = _cancel_qmt_order(config, order_id=order_id)
    overview = get_qmt_virtual_account_overview(db, user_id, account_key=config.key)
    return {
        "message": "QMT 撤单请求已提交",
        "account_key": config.key,
        "cancel_result": result,
        "overview": overview,
    }


def diagnose_qmt_accounts(account_key: str | None = None, run_connect_test: bool = False) -> dict[str, Any]:
    configs = _runtime_configs()
    active_key = _resolve_active_key(configs, account_key)
    items = [_diagnose_single_account(config, run_connect_test=run_connect_test) for config in configs]
    return {
        "active_account_key": active_key,
        "run_connect_test": run_connect_test,
        "items": items,
        "summary": {
            "total": len(items),
            "enabled": sum(1 for item in items if item["enabled"]),
            "ready": sum(1 for item in items if item["ready"]),
            "connected": sum(1 for item in items if item.get("connect_test", {}).get("connected") is True),
        },
        "checked_at": _iso_now(),
    }


def _runtime_configs() -> list[QmtRuntimeConfig]:
    configs: list[QmtRuntimeConfig] = []
    for raw in settings.qmt_accounts():
        configs.append(
            QmtRuntimeConfig(
                key=str(raw.get("key") or "qmt_default").strip() or "qmt_default",
                enabled=bool(raw.get("enabled", False)),
                host=str(raw.get("host") or settings.qmt_host),
                port=int(raw.get("port") or settings.qmt_port or 58610),
                account_id=str(raw.get("account_id") or "").strip(),
                account_type=str(raw.get("account_type") or settings.qmt_account_type or "STOCK").strip() or "STOCK",
                account_name=str(raw.get("account_name") or "QMT 账户").strip() or "QMT 账户",
                userdata_path=str(raw.get("userdata_path") or "").strip(),
                role=str(raw.get("role") or "paper").strip() or "paper",
                bridge_base_url=str(raw.get("bridge_base_url") or "").strip(),
                bridge_token=str(raw.get("bridge_token") or "").strip(),
                refresh_interval_seconds=max(int(raw.get("refresh_interval_seconds") or settings.qmt_refresh_interval_seconds or 10), 5),
            )
        )
    return configs or [
        QmtRuntimeConfig(
            key="qmt_default",
            enabled=False,
            host=settings.qmt_host,
            port=settings.qmt_port,
            account_id="",
            account_type=settings.qmt_account_type or "STOCK",
            account_name="QMT 账户",
            userdata_path="",
            role="paper",
            bridge_base_url=str(settings.qmt_bridge_base_url or "").strip(),
            bridge_token=str(settings.qmt_bridge_token or "").strip(),
            refresh_interval_seconds=max(int(settings.qmt_refresh_interval_seconds or 10), 5),
        )
    ]


def _resolve_runtime_config(account_key: str | None) -> QmtRuntimeConfig:
    configs = _runtime_configs()
    active_key = _resolve_active_key(configs, account_key)
    return _pick_active_config(configs, active_key)


def _pick_active_config(configs: list[QmtRuntimeConfig], account_key: str | None) -> QmtRuntimeConfig:
    for config in configs:
        if config.key == account_key:
            return config
    return configs[0]


def _resolve_active_key(configs: list[QmtRuntimeConfig], account_key: str | None) -> str:
    if account_key:
        return account_key
    default_key = (settings.qmt_default_account_key or "").strip()
    if default_key:
        return default_key
    for config in configs:
        if config.enabled:
            return config.key
    return configs[0].key


def _load_account_payload(
    db: Session,
    user_id: str,
    config: QmtRuntimeConfig,
    *,
    sync_to_imports: bool = False,
) -> dict[str, Any]:
    connection = {
        "account_key": config.key,
        "role": config.role,
        "enabled": config.enabled,
        "provider": "xtquant",
        "host": config.host,
        "port": config.port,
        "account_id": config.account_id,
        "account_type": config.account_type,
        "account_name": config.account_name,
        "userdata_path": config.userdata_path,
        "bridge_base_url": config.bridge_base_url,
        "connected": False,
        "message": "",
    }
    empty = _load_empty_payload(config, connection=connection)
    if not config.enabled:
        connection["message"] = "当前账户未启用，请在 QMT_ACCOUNTS_JSON 或环境变量中打开 enabled。"
        return empty
    if not config.account_id:
        connection["message"] = "缺少 account_id，无法查询账户资产。"
        return empty
    if not config.userdata_path and not config.bridge_base_url:
        host_reachable, reachability_message = _probe_tcp_port(config.host, config.port)
        if host_reachable:
            connection["message"] = "已探测到 QMT 端口可达，但未配置 bridge_base_url / userdata_path，暂无法读取资产与持仓。"
        else:
            connection["message"] = f"缺少 bridge_base_url / userdata_path，且端口探测未通过：{reachability_message}"
        return empty

    try:
        snapshot = _query_qmt_snapshot(config)
    except ImportError as exc:
        connection["message"] = f"xtquant 未安装：{exc}"
        cached = _load_cached_payload(db, user_id, config, connection_override=connection)
        return cached or empty
    except Exception as exc:
        logger.exception("[qmt] fetch overview failed for %s", config.key)
        connection["message"] = f"QMT 连接失败：{exc}"
        cached = _load_cached_payload(db, user_id, config, connection_override=connection)
        return cached or empty

    security_name_map = _security_name_map_from_cache()
    positions = _build_position_items(db, user_id, config, snapshot.get("positions") or [], security_name_map)
    quote_map = _fetch_live_quotes([item["symbol"] for item in positions])
    positions = _apply_quote_metrics(positions, quote_map)
    _sync_position_state(db, user_id, config.account_id, positions)
    if sync_to_imports:
        _sync_qmt_positions_to_imports(db, user_id, config.key, positions)
    account_payload = _build_account_payload(config, snapshot, positions)
    connection["connected"] = True
    connection["message"] = f"已连接 QMT {('模拟' if config.role == 'paper' else '实盘')}账户"
    payload = {
        "connection": connection,
        "account": account_payload,
        "positions": positions,
        "orders": _build_order_items(snapshot.get("orders") or [], security_name_map),
        "trades": _build_trade_items(snapshot.get("trades") or [], security_name_map),
        "summary": {
            "total_asset": account_payload["total_asset"],
            "total_pnl": account_payload["total_pnl"],
            "today_pnl": account_payload["today_pnl"],
            "market_value": account_payload["market_value"],
            "available_cash": account_payload["available_cash"],
            "position_count": len(positions),
        },
        "refresh_interval_seconds": config.refresh_interval_seconds,
        "fetched_at": _iso_now(),
        "last_synced_at": _iso_now(),
        "data_source": "live",
        "is_stale": False,
    }
    _persist_account_snapshot(db, user_id, config, payload)
    return payload


def _load_empty_payload(
    config: QmtRuntimeConfig,
    *,
    connection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_connection = connection or {
        "account_key": config.key,
        "role": config.role,
        "enabled": config.enabled,
        "provider": "xtquant",
        "host": config.host,
        "port": config.port,
        "account_id": config.account_id,
        "account_type": config.account_type,
        "account_name": config.account_name,
        "userdata_path": config.userdata_path,
        "bridge_base_url": config.bridge_base_url,
        "connected": False,
        "message": "",
    }
    return {
        "connection": active_connection,
        "account": None,
        "positions": [],
        "orders": [],
        "trades": [],
        "summary": {
            "total_asset": 0.0,
            "total_pnl": 0.0,
            "today_pnl": 0.0,
            "market_value": 0.0,
            "available_cash": 0.0,
            "position_count": 0,
        },
        "refresh_interval_seconds": config.refresh_interval_seconds,
        "fetched_at": _iso_now(),
        "last_synced_at": None,
        "data_source": "empty",
        "is_stale": True,
    }


def _persist_account_snapshot(
    db: Session,
    user_id: str,
    config: QmtRuntimeConfig,
    payload: dict[str, Any],
) -> None:
    fetched_at = _parse_iso_datetime(payload.get("last_synced_at") or payload.get("fetched_at"))
    row = (
        db.query(QmtAccountSnapshotDB)
        .filter(
            QmtAccountSnapshotDB.user_id == user_id,
            QmtAccountSnapshotDB.account_key == config.key,
        )
        .first()
    )
    if row is None:
        row = QmtAccountSnapshotDB(
            id=uuid4().hex,
            user_id=user_id,
            account_key=config.key,
        )
        db.add(row)
    row.role = config.role
    row.account_id = config.account_id
    row.connection_json = dict(payload.get("connection") or {})
    row.account_json = dict(payload.get("account") or {}) if payload.get("account") else None
    row.positions_json = list(payload.get("positions") or [])
    row.orders_json = list(payload.get("orders") or [])
    row.trades_json = list(payload.get("trades") or [])
    row.summary_json = dict(payload.get("summary") or {})
    row.fetched_at = fetched_at
    db.commit()


def _load_cached_payload(
    db: Session,
    user_id: str,
    config: QmtRuntimeConfig,
    *,
    connection_override: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    row = (
        db.query(QmtAccountSnapshotDB)
        .filter(
            QmtAccountSnapshotDB.user_id == user_id,
            QmtAccountSnapshotDB.account_key == config.key,
        )
        .first()
    )
    if row is None:
        return None
    connection = dict(row.connection_json or {})
    if connection_override:
        connection.update(connection_override)
    connection["connected"] = False
    base_message = str(connection_override.get("message") if connection_override else "").strip()
    if row.fetched_at:
        cached_label = row.fetched_at.astimezone(timezone.utc).isoformat()
        connection["message"] = f"{base_message or 'QMT 当前不可用'}，已回退到最近快照（{cached_label}）"
    else:
        connection["message"] = f"{base_message or 'QMT 当前不可用'}，已回退到本地缓存"
    return {
        "connection": connection,
        "account": dict(row.account_json or {}) if row.account_json else None,
        "positions": list(row.positions_json or []),
        "orders": list(row.orders_json or []),
        "trades": list(row.trades_json or []),
        "summary": dict(row.summary_json or {}),
        "refresh_interval_seconds": config.refresh_interval_seconds,
        "fetched_at": _iso_now(),
        "last_synced_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "data_source": "cache",
        "is_stale": True,
    }


def _diagnose_single_account(config: QmtRuntimeConfig, *, run_connect_test: bool) -> dict[str, Any]:
    userdata_path_exists = bool(config.userdata_path) and os.path.exists(config.userdata_path)
    xtquant_installed, xtquant_message = _check_xtquant_available()
    tcp_reachable, tcp_message = _probe_tcp_port(config.host, config.port)
    bridge_reachable, bridge_message = _probe_bridge(config)
    checks = {
        "enabled": config.enabled,
        "account_id_configured": bool(config.account_id),
        "userdata_path_configured": bool(config.userdata_path),
        "userdata_path_exists": userdata_path_exists,
        "xtquant_installed": xtquant_installed,
        "tcp_port_reachable": tcp_reachable,
        "bridge_configured": bool(config.bridge_base_url),
        "bridge_reachable": bridge_reachable,
    }
    warnings: list[str] = []
    if config.enabled and not config.account_id:
        warnings.append("缺少 account_id")
    if config.enabled and not config.userdata_path and not config.bridge_base_url:
        warnings.append("缺少 bridge_base_url / userdata_path")
    if config.enabled and config.userdata_path and not userdata_path_exists:
        warnings.append("userdata_path 不存在或当前运行环境无法访问")
    if config.enabled and not xtquant_installed and not config.bridge_base_url:
        warnings.append("xtquant 未安装")
    if config.enabled and not tcp_reachable:
        warnings.append("QMT 端口不可达")
    if config.enabled and config.bridge_base_url and not bridge_reachable:
        warnings.append("QMT bridge 不可达")

    connect_test = {
        "attempted": False,
        "connected": False,
        "message": "未执行连接测试",
    }
    can_connect = (
        config.enabled
        and checks["account_id_configured"]
        and (
            bool(config.bridge_base_url and bridge_reachable)
            or bool(config.userdata_path and userdata_path_exists and xtquant_installed)
        )
    )
    if run_connect_test and can_connect:
        connect_test = _run_connect_diagnostic(config)

    ready = (
        config.enabled
        and checks["account_id_configured"]
        and (
            bool(config.bridge_base_url and bridge_reachable)
            or bool(config.userdata_path and userdata_path_exists and xtquant_installed)
        )
    )
    return {
        "account_key": config.key,
        "role": config.role,
        "enabled": config.enabled,
        "account_id": config.account_id,
        "account_name": config.account_name,
        "host": config.host,
        "port": config.port,
        "userdata_path": config.userdata_path,
        "bridge_base_url": config.bridge_base_url,
        "ready": ready,
        "checks": checks,
        "warnings": warnings,
        "xtquant_message": xtquant_message,
        "tcp_probe": {
            "reachable": tcp_reachable,
            "message": tcp_message,
        },
        "bridge_probe": {
            "configured": bool(config.bridge_base_url),
            "reachable": bridge_reachable,
            "message": bridge_message,
        },
        "connect_test": connect_test,
    }


def _check_xtquant_available() -> tuple[bool, str]:
    try:
        import xtquant  # type: ignore

        version = getattr(xtquant, "__version__", None)
        return True, f"xtquant 已安装{f'，版本 {version}' if version else ''}"
    except Exception as exc:
        return False, f"xtquant 不可用：{exc}"


def _run_connect_diagnostic(config: QmtRuntimeConfig) -> dict[str, Any]:
    try:
        _query_qmt_snapshot(config)
        return {
            "attempted": True,
            "connected": True,
            "message": "连接成功，可读取账户资产与持仓",
        }
    except Exception as exc:
        logger.warning("[qmt] diagnostic connect failed for %s: %s", config.key, exc)
        return {
            "attempted": True,
            "connected": False,
            "message": f"连接失败：{exc}",
        }


def _probe_tcp_port(host: str, port: int, timeout: float = 1.5) -> tuple[bool, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        return True, f"{host}:{port} 可达"
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _probe_bridge(config: QmtRuntimeConfig, timeout: float = 2.0) -> tuple[bool, str]:
    base_url = str(config.bridge_base_url or "").strip().rstrip("/")
    if not base_url:
        return False, "未配置 bridge_base_url"
    headers = {}
    if config.bridge_token:
        headers["Authorization"] = f"Bearer {config.bridge_token}"
    try:
        response = requests.get(f"{base_url}/health", headers=headers, timeout=timeout)
        response.raise_for_status()
        return True, f"{base_url}/health 可达"
    except Exception as exc:
        return False, str(exc)


def _query_qmt_snapshot(config: QmtRuntimeConfig) -> dict[str, Any]:
    if config.bridge_base_url:
        return _query_qmt_snapshot_via_bridge(config)
    return _query_qmt_snapshot_via_local_xttrader(config)


def _submit_qmt_order(
    config: QmtRuntimeConfig,
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float | None,
    price_type: str,
    strategy_name: str | None,
    order_remark: str | None,
) -> dict[str, Any]:
    if config.bridge_base_url:
        return _submit_qmt_order_via_bridge(
            config,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            price_type=price_type,
            strategy_name=strategy_name,
            order_remark=order_remark,
        )
    return _submit_qmt_order_via_local_xttrader(
        config,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        price_type=price_type,
        strategy_name=strategy_name,
        order_remark=order_remark,
    )


def _cancel_qmt_order(config: QmtRuntimeConfig, *, order_id: str) -> dict[str, Any]:
    if config.bridge_base_url:
        return _cancel_qmt_order_via_bridge(config, order_id=order_id)
    return _cancel_qmt_order_via_local_xttrader(config, order_id=order_id)


def _query_qmt_snapshot_via_bridge(config: QmtRuntimeConfig) -> dict[str, Any]:
    base_url = str(config.bridge_base_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("bridge_base_url 为空")
    headers = {}
    if config.bridge_token:
        headers["Authorization"] = f"Bearer {config.bridge_token}"
    response = requests.get(
        f"{base_url}/snapshot",
        params={"account_id": config.account_id, "account_type": config.account_type, "account_key": config.key},
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "fund": payload.get("fund") or {},
        "positions": payload.get("positions") or [],
        "asset": payload.get("asset") or {},
        "orders": payload.get("orders") or [],
        "trades": payload.get("trades") or [],
        "bridge": payload.get("bridge") or {},
    }


def _submit_qmt_order_via_bridge(
    config: QmtRuntimeConfig,
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float | None,
    price_type: str,
    strategy_name: str | None,
    order_remark: str | None,
) -> dict[str, Any]:
    base_url = str(config.bridge_base_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("bridge_base_url 为空")
    headers = {}
    if config.bridge_token:
        headers["Authorization"] = f"Bearer {config.bridge_token}"
    response = requests.post(
        f"{base_url}/orders",
        json={
            "account_id": config.account_id,
            "account_type": config.account_type,
            "account_key": config.key,
            "symbol": str(symbol or "").strip().upper(),
            "side": side,
            "quantity": int(quantity),
            "price": float(price) if price is not None else None,
            "price_type": price_type,
            "strategy_name": strategy_name,
            "order_remark": order_remark,
        },
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "success": bool(payload.get("success", True)),
        "order_id": str(payload.get("order_id") or ""),
        "result": payload.get("result"),
        "request": payload.get("request") or {},
        "bridge": payload.get("bridge") or {},
        "raw": payload,
    }


def _cancel_qmt_order_via_bridge(config: QmtRuntimeConfig, *, order_id: str) -> dict[str, Any]:
    base_url = str(config.bridge_base_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("bridge_base_url 为空")
    headers = {}
    if config.bridge_token:
        headers["Authorization"] = f"Bearer {config.bridge_token}"
    response = requests.post(
        f"{base_url}/orders/{order_id}/cancel",
        params={"account_id": config.account_id, "account_type": config.account_type, "account_key": config.key},
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "success": bool(payload.get("success", True)),
        "order_id": str(payload.get("order_id") or order_id),
        "result": payload.get("result"),
        "bridge": payload.get("bridge") or {},
        "raw": payload,
    }


def _query_qmt_snapshot_via_local_xttrader(config: QmtRuntimeConfig) -> dict[str, Any]:
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount

    session_id = int(time.time() * 1000) % 100000000
    trader = XtQuantTrader(config.userdata_path, session_id)
    account = StockAccount(config.account_id, config.account_type)
    start = getattr(trader, "start", None)
    if callable(start):
        start()
    connect_result = getattr(trader, "connect")()
    if connect_result not in (0, None):
        raise RuntimeError(f"connect 返回异常：{connect_result}")
    subscribe = getattr(trader, "subscribe", None)
    if callable(subscribe):
        subscribe(account)

    fund = None
    positions: list[Any] | None = None
    asset = None
    orders: list[Any] | None = None
    trades: list[Any] | None = None
    try:
        query_com_fund = getattr(trader, "query_com_fund", None)
        if callable(query_com_fund):
            fund = query_com_fund(account)
        query_com_position = getattr(trader, "query_com_position", None)
        if callable(query_com_position):
            positions = query_com_position(account)
        asset = trader.query_stock_asset(account)
        if positions in (None, []):
            positions = trader.query_stock_positions(account)
        query_stock_orders = getattr(trader, "query_stock_orders", None)
        if callable(query_stock_orders):
            orders = query_stock_orders(account)
        query_stock_trades = getattr(trader, "query_stock_trades", None)
        if callable(query_stock_trades):
            trades = query_stock_trades(account)
    finally:
        stop = getattr(trader, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                logger.debug("[qmt] trader.stop failed", exc_info=True)
    return {"fund": fund, "positions": positions or [], "asset": asset, "orders": orders or [], "trades": trades or []}


def _submit_qmt_order_via_local_xttrader(
    config: QmtRuntimeConfig,
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float | None,
    price_type: str,
    strategy_name: str | None,
    order_remark: str | None,
) -> dict[str, Any]:
    from xtquant import xtconstant
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount

    symbol_value = str(symbol or "").strip().upper()
    side_key = str(side or "").strip().lower()
    if side_key in {"buy", "long_buy", "b"}:
        order_type = getattr(xtconstant, "STOCK_BUY", 23)
    elif side_key in {"sell", "long_sell", "s"}:
        order_type = getattr(xtconstant, "STOCK_SELL", 24)
    else:
        raise RuntimeError(f"不支持的 side: {side}")

    price_key = str(price_type or "limit").strip().lower()
    exchange = symbol_value.split(".")[-1] if "." in symbol_value else ""
    price_mode_map = {
        "limit": getattr(xtconstant, "FIX_PRICE", 11),
        "latest": getattr(xtconstant, "LATEST_PRICE", getattr(xtconstant, "FIX_PRICE", 11)),
        "opponent": getattr(xtconstant, "MARKET_PEER_PRICE_FIRST", getattr(xtconstant, "FIX_PRICE", 11)),
        "self_best": getattr(xtconstant, "MARKET_MINE_PRICE_FIRST", getattr(xtconstant, "FIX_PRICE", 11)),
        "best5_cancel": getattr(
            xtconstant,
            "MARKET_SH_CONVERT_5_CANCEL" if exchange == "SH" else "MARKET_SZ_CONVERT_5_CANCEL",
            getattr(xtconstant, "FIX_PRICE", 11),
        ),
    }
    if price_key not in price_mode_map:
        raise RuntimeError(f"不支持的 price_type: {price_type}")

    session_id = int(time.time() * 1000) % 100000000
    trader = XtQuantTrader(config.userdata_path, session_id)
    account = StockAccount(config.account_id, config.account_type)
    start = getattr(trader, "start", None)
    if callable(start):
        start()
    connect_result = getattr(trader, "connect")()
    if connect_result not in (0, None):
        raise RuntimeError(f"connect 返回异常：{connect_result}")
    subscribe = getattr(trader, "subscribe", None)
    if callable(subscribe):
        subscribe(account)
    try:
        order_stock = getattr(trader, "order_stock", None)
        if not callable(order_stock):
            raise RuntimeError("xttrader.order_stock 不可用")
        result = order_stock(
            account,
            symbol_value,
            order_type,
            int(quantity),
            price_mode_map[price_key],
            float(price or 0.0),
            str(strategy_name or "TradingAgents"),
            str(order_remark or ""),
        )
    finally:
        stop = getattr(trader, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                logger.debug("[qmt] trader.stop failed", exc_info=True)
    return {
        "success": True,
        "order_id": str(result),
        "result": result,
        "request": {
            "symbol": symbol_value,
            "side": side,
            "quantity": int(quantity),
            "price": price,
            "price_type": price_type,
            "strategy_name": strategy_name,
            "order_remark": order_remark,
        },
    }


def _cancel_qmt_order_via_local_xttrader(config: QmtRuntimeConfig, *, order_id: str) -> dict[str, Any]:
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount

    session_id = int(time.time() * 1000) % 100000000
    trader = XtQuantTrader(config.userdata_path, session_id)
    account = StockAccount(config.account_id, config.account_type)
    start = getattr(trader, "start", None)
    if callable(start):
        start()
    connect_result = getattr(trader, "connect")()
    if connect_result not in (0, None):
        raise RuntimeError(f"connect 返回异常：{connect_result}")
    subscribe = getattr(trader, "subscribe", None)
    if callable(subscribe):
        subscribe(account)
    try:
        cancel_order_stock = getattr(trader, "cancel_order_stock", None)
        if not callable(cancel_order_stock):
            raise RuntimeError("xttrader.cancel_order_stock 不可用")
        cancel_arg: Any = int(order_id) if str(order_id).isdigit() else order_id
        result = cancel_order_stock(account, cancel_arg)
    finally:
        stop = getattr(trader, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                logger.debug("[qmt] trader.stop failed", exc_info=True)
    return {
        "success": True,
        "order_id": str(order_id),
        "result": result,
    }


def _build_position_items(
    db: Session,
    user_id: str,
    config: QmtRuntimeConfig,
    raw_positions: list[Any],
    security_name_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    tracked_states = {
        row.symbol: row
        for row in db.query(VirtualPositionStateDB).filter(
            VirtualPositionStateDB.user_id == user_id,
            VirtualPositionStateDB.broker == "qmt",
            VirtualPositionStateDB.account_id == config.account_id,
        ).all()
    }
    items: list[dict[str, Any]] = []
    for raw in raw_positions:
        payload = raw if isinstance(raw, dict) else _object_to_dict(raw)
        symbol = _normalize_symbol(payload.get("stockCode") or payload.get("stock_code"))
        quantity = _to_float(payload.get("totalAmt"), payload.get("volume"))
        if not symbol or quantity in (None, 0):
            continue
        available = _to_float(payload.get("enableAmount"), payload.get("can_use_volume"))
        current_price = _to_float(payload.get("lastPrice"))
        avg_price = _to_float(payload.get("costPrice"), payload.get("avg_price"), payload.get("open_price"))
        market_value = _to_float(payload.get("marketValue"), payload.get("market_value"))
        if market_value is None and current_price is not None and quantity is not None:
            market_value = round(current_price * quantity, 2)
        total_pnl = _to_float(payload.get("income"))
        if total_pnl is None and current_price is not None and avg_price is not None:
            total_pnl = round((current_price - avg_price) * quantity, 2)
        total_pnl_pct = None
        if current_price is not None and avg_price not in (None, 0):
            total_pnl_pct = round(((current_price - avg_price) / avg_price) * 100, 2)
        state = tracked_states.get(symbol)
        first_seen_at = state.first_seen_at if state and (state.last_quantity or 0) > 0 else datetime.now(timezone.utc)
        holding_days = max((datetime.now(timezone.utc).date() - first_seen_at.date()).days + 1, 1)
        break_even_rise_pct = 0.0
        if current_price not in (None, 0) and avg_price and current_price < avg_price:
            break_even_rise_pct = round(((avg_price / current_price) - 1) * 100, 2)
        items.append(
            {
                "symbol": symbol,
                "name": _resolve_security_name(payload, symbol, security_name_map),
                "account_id": config.account_id,
                "current_position": round(float(quantity), 2),
                "available_position": round(float(available or 0.0), 2),
                "average_cost": round(float(avg_price or 0.0), 4),
                "current_price": round(float(current_price or 0.0), 4) if current_price is not None else None,
                "market_value": round(float(market_value or 0.0), 2),
                "total_pnl": round(float(total_pnl or 0.0), 2),
                "total_pnl_pct": total_pnl_pct,
                "today_pnl": None,
                "today_pnl_pct": None,
                "holding_days": holding_days,
                "break_even_rise_pct": break_even_rise_pct,
                "position_pct": None,
                "raw": payload,
            }
        )
    total_market_value = sum(float(item["market_value"] or 0.0) for item in items)
    if total_market_value > 0:
        for item in items:
            item["position_pct"] = round((float(item["market_value"] or 0.0) / total_market_value) * 100, 2)
    items.sort(key=lambda item: float(item.get("market_value") or 0.0), reverse=True)
    return items


def _build_order_items(raw_orders: list[Any], security_name_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in raw_orders:
        payload = raw if isinstance(raw, dict) else _object_to_dict(raw)
        symbol = _normalize_symbol(payload.get("stockCode") or payload.get("stock_code") or payload.get("symbol"))
        if not symbol:
            continue
        order_time = payload.get("orderTime") or payload.get("insert_time") or payload.get("order_time") or payload.get("created_at")
        items.append(
            {
                "order_id": str(payload.get("orderId") or payload.get("order_id") or payload.get("entrust_no") or ""),
                "symbol": symbol,
                "name": _resolve_security_name(payload, symbol, security_name_map),
                "side": _normalize_side(payload.get("orderType") or payload.get("side") or payload.get("entrust_bs")),
                "status": str(payload.get("orderStatus") or payload.get("status") or payload.get("status_name") or "unknown"),
                "price": _to_float(payload.get("orderPrice"), payload.get("price")),
                "quantity": _to_float(payload.get("orderVolume"), payload.get("volume"), payload.get("orderQty")),
                "filled_quantity": _to_float(payload.get("tradedVolume"), payload.get("business_amount"), payload.get("filled_quantity")),
                "amount": _to_float(payload.get("orderAmount"), payload.get("amount")),
                "order_time": str(order_time) if order_time is not None else None,
                "can_cancel": _is_order_cancelable(payload),
                "raw": payload,
            }
        )
    items.sort(key=lambda item: str(item.get("order_time") or ""), reverse=True)
    return items[:50]


def _build_trade_items(raw_trades: list[Any], security_name_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in raw_trades:
        payload = raw if isinstance(raw, dict) else _object_to_dict(raw)
        symbol = _normalize_symbol(payload.get("stockCode") or payload.get("stock_code") or payload.get("symbol"))
        if not symbol:
            continue
        trade_time = payload.get("tradedTime") or payload.get("trade_time") or payload.get("business_time") or payload.get("executed_at")
        quantity = _to_float(payload.get("tradedVolume"), payload.get("volume"), payload.get("business_amount"))
        price = _to_float(payload.get("tradedPrice"), payload.get("price"), payload.get("business_price"))
        items.append(
            {
                "trade_id": str(payload.get("tradedId") or payload.get("trade_id") or payload.get("business_no") or ""),
                "order_id": str(payload.get("orderId") or payload.get("order_id") or payload.get("entrust_no") or ""),
                "symbol": symbol,
                "name": _resolve_security_name(payload, symbol, security_name_map),
                "side": _normalize_side(payload.get("orderType") or payload.get("side") or payload.get("entrust_bs")),
                "price": price,
                "quantity": quantity,
                "amount": round(float(quantity or 0.0) * float(price or 0.0), 2) if quantity is not None and price is not None else _to_float(payload.get("amount")),
                "trade_time": str(trade_time) if trade_time is not None else None,
                "raw": payload,
            }
        )
    items.sort(key=lambda item: str(item.get("trade_time") or ""), reverse=True)
    return items[:50]


def _is_order_cancelable(payload: dict[str, Any]) -> bool:
    order_id = str(payload.get("orderId") or payload.get("order_id") or payload.get("entrust_no") or "").strip()
    if not order_id:
        return False
    status_text = str(payload.get("orderStatus") or payload.get("status") or payload.get("status_name") or "").strip().lower()
    if not status_text:
        return True
    terminal_keywords = ("filled", "cancel", "rejected", "invalid", "expired", "done", "success_all")
    return not any(keyword in status_text for keyword in terminal_keywords)


def _apply_quote_metrics(
    items: list[dict[str, Any]],
    quote_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        quote = quote_map.get(item["symbol"]) or {}
        resolved_name = _resolve_security_name(quote, item["symbol"], _security_name_map_from_cache())
        current_price = _to_float(quote.get("price"), item.get("current_price"))
        previous_close = _to_float(quote.get("previous_close"))
        price_change = _to_float(quote.get("change"))
        if price_change is None and current_price is not None and previous_close not in (None, 0):
            price_change = round(current_price - previous_close, 4)
        today_pnl = round(float(price_change or 0.0) * float(item.get("current_position") or 0.0), 2) if price_change is not None else None
        today_pnl_pct = _to_float(quote.get("change_pct"))
        total_pnl = item.get("total_pnl")
        avg_price = _to_float(item.get("average_cost"))
        if current_price is not None and avg_price not in (None, 0):
            total_pnl = round((current_price - avg_price) * float(item.get("current_position") or 0.0), 2)
            total_pnl_pct = round(((current_price - avg_price) / avg_price) * 100, 2)
            item["break_even_rise_pct"] = round(max((avg_price / current_price) - 1, 0) * 100, 2) if current_price > 0 else None
        market_value = item.get("market_value")
        if current_price is not None:
            market_value = round(current_price * float(item.get("current_position") or 0.0), 2)
        enriched.append(
            {
                **item,
                "name": resolved_name if resolved_name and not _looks_like_symbol(resolved_name) else item.get("name"),
                "current_price": round(float(current_price), 4) if current_price is not None else item.get("current_price"),
                "market_value": market_value,
                "total_pnl": total_pnl,
                "total_pnl_pct": total_pnl_pct,
                "today_pnl": today_pnl,
                "today_pnl_pct": today_pnl_pct,
                "previous_close": previous_close,
                "quote_time": quote.get("quote_time"),
                "quote_source": quote.get("source"),
            }
        )
    return enriched


def _build_account_payload(
    config: QmtRuntimeConfig,
    snapshot: dict[str, Any],
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    fund = snapshot.get("fund") or {}
    asset = snapshot.get("asset")
    asset_payload = _object_to_dict(asset) if asset is not None else {}
    total_asset = _to_float(fund.get("assetBalance"), asset_payload.get("total_asset"))
    market_value = _to_float(fund.get("marketValue"), asset_payload.get("market_value"))
    available_cash = _to_float(fund.get("enableBalance"), asset_payload.get("cash"))
    if market_value is None:
        market_value = round(sum(float(item.get("market_value") or 0.0) for item in positions), 2)
    if available_cash is None:
        available_cash = 0.0
    if total_asset is None:
        total_asset = round(float(available_cash) + float(market_value or 0.0), 2)
    total_pnl = round(sum(float(item.get("total_pnl") or 0.0) for item in positions), 2)
    today_pnl = round(sum(float(item.get("today_pnl") or 0.0) for item in positions if item.get("today_pnl") is not None), 2)
    total_cost = sum(float(item.get("average_cost") or 0.0) * float(item.get("current_position") or 0.0) for item in positions)
    total_pnl_pct = round((total_pnl / total_cost) * 100, 2) if total_cost > 0 else 0.0
    return {
        "account_key": config.key,
        "role": config.role,
        "broker": "QMT",
        "mode": "极简模式 / Python 策略端",
        "account_name": config.account_name,
        "account_id": config.account_id,
        "security_account_name": config.account_name,
        "total_asset": round(float(total_asset or 0.0), 2),
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "today_pnl": today_pnl,
        "market_value": round(float(market_value or 0.0), 2),
        "available_cash": round(float(available_cash or 0.0), 2),
        "position_count": len(positions),
    }


def _sync_position_state(
    db: Session,
    user_id: str,
    account_id: str,
    positions: list[dict[str, Any]],
) -> None:
    now = datetime.now(timezone.utc)
    rows = db.query(VirtualPositionStateDB).filter(
        VirtualPositionStateDB.user_id == user_id,
        VirtualPositionStateDB.broker == "qmt",
        VirtualPositionStateDB.account_id == account_id,
    ).all()
    state_map = {row.symbol: row for row in rows}
    active_symbols = {item["symbol"] for item in positions}

    for item in positions:
        row = state_map.get(item["symbol"])
        if row is None:
            row = VirtualPositionStateDB(
                id=uuid4().hex,
                user_id=user_id,
                broker="qmt",
                account_id=account_id,
                symbol=item["symbol"],
                first_seen_at=now,
                created_at=now,
            )
            db.add(row)
        elif not row.first_seen_at or (row.last_quantity or 0) <= 0:
            row.first_seen_at = now
        row.last_seen_at = now
        row.last_quantity = float(item.get("current_position") or 0.0)
        row.last_price = _to_float(item.get("current_price"))
        row.last_market_value = _to_float(item.get("market_value"))
        row.last_payload_json = item.get("raw")

    for row in rows:
        if row.symbol in active_symbols:
            continue
        row.last_seen_at = now
        row.last_quantity = 0.0

    db.commit()


def _sync_qmt_positions_to_imports(db: Session, user_id: str, account_key: str, positions: list[dict[str, Any]]) -> None:
    config = _resolve_runtime_config(account_key)
    source = _source_name(account_key, config.role)
    payload = [
        {
            "symbol": item["symbol"],
            "name": item.get("name"),
            "current_position": item.get("current_position"),
            "available_position": item.get("available_position"),
            "average_cost": item.get("average_cost"),
            "market_value": item.get("market_value"),
            "current_position_pct": item.get("position_pct"),
        }
        for item in positions
    ]
    if not payload:
        db.query(ImportedPortfolioPositionDB).filter(
            ImportedPortfolioPositionDB.user_id == user_id,
            ImportedPortfolioPositionDB.source == source,
        ).delete()
        db.commit()
        return
    portfolio_import_service.sync_positions(
        db=db,
        user_id=user_id,
        positions=payload,
        source=source,
        auto_apply_scheduled=True,
    )


def _source_name(account_key: str, role: str = "paper") -> str:
    key = (account_key or "qmt_default").strip() or "qmt_default"
    prefix = "qmt_live" if str(role or "").strip().lower() == "live" else SOURCE_NAME
    return f"{prefix}:{key}"


def _fetch_live_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    try:
        raw = route_to_vendor("get_realtime_quotes", symbols)
        if isinstance(raw, dict):
            return raw
        import json
        return json.loads(raw)
    except Exception as exc:
        logger.warning("[qmt] realtime quote fetch failed: %s", exc)
        return {}


def _normalize_symbol(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if "." in text:
        return text
    if len(text) == 6:
        if text.startswith("6"):
            return f"{text}.SH"
        if text.startswith(("0", "3")):
            return f"{text}.SZ"
        if text.startswith(("4", "8")):
            return f"{text}.BJ"
    return text


def _security_name_map_from_cache() -> dict[str, str]:
    try:
        return get_reverse_stock_map_cached_only()
    except Exception:
        logger.debug("[qmt] get stock name cache failed", exc_info=True)
        return {}


def _resolve_security_name(
    payload: dict[str, Any],
    symbol: str,
    security_name_map: dict[str, str] | None = None,
) -> str:
    for key in (
        "stockName",
        "stock_name",
        "security_name",
        "name",
        "instrument_name",
        "InstrumentName",
        "m_strStockName",
        "m_strInstrumentName",
    ):
        value = str(payload.get(key) or "").strip()
        if value and not _looks_like_symbol(value):
            return value
    name_map = security_name_map or {}
    normalized_symbol = _normalize_symbol(symbol) or symbol
    code = normalized_symbol.split(".", 1)[0]
    return (
        name_map.get(normalized_symbol)
        or name_map.get(code)
        or name_map.get(str(symbol or "").strip().upper())
        or normalized_symbol
    )


def _looks_like_symbol(value: str) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return False
    if text.isdigit() and len(text) == 6:
        return True
    if len(text) == 9 and text[:6].isdigit() and text[6:] in (".SH", ".SZ", ".BJ"):
        return True
    return False


def _normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"23", "buy", "b", "买入"}:
        return "buy"
    if text in {"24", "sell", "s", "卖出"}:
        return "sell"
    return text or "unknown"


def _object_to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    data: dict[str, Any] = {}
    for key in dir(obj):
        if key.startswith("_"):
            continue
        try:
            value = getattr(obj, key)
        except Exception:
            continue
        if callable(value):
            continue
        if isinstance(value, (str, int, float, bool, dict, list)) or value is None:
            data[key] = value
    return data


def _to_float(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                continue
            return number
        except Exception:
            continue
    return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None
