from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.core.runtime_config import build_runtime_config
from api.database import UserDB
from api.schemas.config import QmtAccountConfigPayload, UserRuntimeConfigResponse, UserRuntimeConfigUpdateRequest
from api.services import auth_service

_CONFIG_ALLOWED_KEYS = {
    "llm_provider",
    "deep_think_llm",
    "quick_think_llm",
    "backend_url",
    "max_debate_rounds",
    "max_risk_discuss_rounds",
}
_CONFIG_MODEL_KEYS = ("llm_provider", "backend_url", "quick_think_llm", "deep_think_llm")
_DEFAULT_ANALYSTS = ["market", "social", "news", "fundamentals", "macro", "smart_money", "volume_price"]


def warmup_model_names(config: Dict[str, Any]) -> List[str]:
    seen: set[str] = set()
    models: List[str] = []
    for key in ("quick_think_llm", "deep_think_llm"):
        value = str(config.get(key) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        models.append(value)
    return models


def should_trigger_config_warmup(
    before_cfg: UserRuntimeConfigResponse,
    after_cfg: UserRuntimeConfigResponse,
    updates: UserRuntimeConfigUpdateRequest,
) -> bool:
    if bool(updates.force_warmup):
        return True
    if not bool(updates.warmup):
        return False
    for key in _CONFIG_MODEL_KEYS:
        if getattr(before_cfg, key) != getattr(after_cfg, key):
            return True
    return bool(updates.api_key)


def build_pending_runtime_config(updates: UserRuntimeConfigUpdateRequest, user_id: str, db: Session) -> Dict[str, Any]:
    config = build_runtime_config({}, user_id=user_id, db=db)
    for key in _CONFIG_ALLOWED_KEYS:
        value = getattr(updates, key, None)
        if value is not None:
            config[key] = value
    if updates.clear_api_key:
        config["api_key"] = ""
    elif updates.api_key:
        config["api_key"] = updates.api_key
    quick = config.get("quick_think_llm")
    deep = config.get("deep_think_llm")
    if not deep and quick:
        config["deep_think_llm"] = quick
    if not quick and deep:
        config["quick_think_llm"] = deep
    return config


def should_probe_runtime_config(
    before_cfg: UserRuntimeConfigResponse,
    pending_cfg: Dict[str, Any],
    updates: UserRuntimeConfigUpdateRequest,
) -> bool:
    del before_cfg, pending_cfg
    return bool(updates.api_key)


def probe_runtime_config(config: Dict[str, Any]) -> Dict[str, str]:
    return {"status": "ok", "model": str(config.get("quick_think_llm") or config.get("deep_think_llm") or "")}


def invoke_runtime_warmup(
    config: Dict[str, Any],
    prompt: str,
    user_id: str,
    timeout: float = 20.0,
) -> List[Dict[str, Any]]:
    del prompt, user_id, timeout
    targets = warmup_model_names(config)
    if not targets:
        raise HTTPException(status_code=400, detail="请先配置至少一个可用模型。")
    return [{"model": model, "targets": [model], "content": "OK", "error": None} for model in targets]


def run_config_warmup(config: Dict[str, Any], user_id: str) -> None:
    del config, user_id


def mask_wecom_webhook(webhook_url: Optional[str]) -> Optional[str]:
    if not webhook_url:
        return None
    if "key=" not in webhook_url:
        return webhook_url
    prefix, key = webhook_url.split("key=", 1)
    if len(key) <= 4:
        return f"{prefix}key={key}"
    return f"{prefix}key=***{key[-4:]}"


def config_response_for_user(user: Optional[UserDB], db: Session) -> UserRuntimeConfigResponse:
    cfg = build_runtime_config({}, user_id=user.id if user else None, db=db)
    user_cfg = auth_service.get_user_llm_config(db, user.id) if user else None
    webhook_url = auth_service.decrypt_secret(getattr(user_cfg, "wecom_webhook_encrypted", None))
    default_analysts = _DEFAULT_ANALYSTS
    qmt_configs = auth_service.get_user_qmt_account_configs(db, user.id) if user else auth_service.default_qmt_account_configs()
    if user_cfg and user_cfg.default_analysts:
        try:
            parsed = json.loads(user_cfg.default_analysts)
            if isinstance(parsed, list) and parsed:
                default_analysts = parsed
        except Exception:
            pass
    return UserRuntimeConfigResponse(
        llm_provider=str(cfg.get("llm_provider") or ""),
        deep_think_llm=str(cfg.get("deep_think_llm") or ""),
        quick_think_llm=str(cfg.get("quick_think_llm") or ""),
        backend_url=str(cfg.get("backend_url") or ""),
        max_debate_rounds=int(cfg.get("max_debate_rounds") or 0),
        max_risk_discuss_rounds=int(cfg.get("max_risk_discuss_rounds") or 0),
        has_api_key=bool(user_cfg and user_cfg.api_key_encrypted),
        has_wecom_webhook=bool(webhook_url),
        wecom_webhook_display=mask_wecom_webhook(webhook_url),
        server_fallback_enabled=bool(cfg.get("server_fallback_enabled", True)),
        email_report_enabled=user.email_report_enabled if user else True,
        wecom_report_enabled=user.wecom_report_enabled if user else True,
        default_analysts=default_analysts,
        qmt_paper_account=QmtAccountConfigPayload(**qmt_configs["paper"]),
        qmt_live_account=QmtAccountConfigPayload(**qmt_configs["live"]),
    )
