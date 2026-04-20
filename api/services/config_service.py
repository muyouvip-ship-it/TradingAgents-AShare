from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.database import UserDB
from api.schemas.config import (
    UserRuntimeConfigResponse,
    UserRuntimeConfigUpdateRequest,
)
from api.core.runtime_config import build_runtime_config
from api.services import auth_service

_CONFIG_ALLOWED_KEYS = {
    "llm_provider", "deep_think_llm", "quick_think_llm",
    "backend_url", "max_debate_rounds", "max_risk_discuss_rounds",
}
_CONFIG_PREFERENCE_KEYS = {"email_report_enabled", "wecom_report_enabled"}
_CONFIG_MODEL_KEYS = ("llm_provider", "backend_url", "quick_think_llm", "deep_think_llm")
_CONFIG_MODEL_LABELS = {
    "quick_think_llm": "常规模型",
    "deep_think_llm": "推理模型",
}
_CONFIG_PROBE_TIMEOUT_SECONDS = 12.0
_CONFIG_PROBE_PROMPT = "Reply with the single word OK."
_CONFIG_WARMUP_TIMEOUT_SECONDS = 20.0
_CONFIG_WARMUP_PROMPT = "Reply with the single word OK."


def mask_secret_value(value: Optional[str], *, head: int = 4, tail: int = 4) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) <= head + tail:
        return "*" * max(6, len(normalized))
    return f"{normalized[:head]}{'*' * max(6, len(normalized) - head - tail)}{normalized[-tail:]}"


def mask_wecom_webhook(webhook_url: Optional[str]) -> Optional[str]:
    normalized = str(webhook_url or "").strip()
    if not normalized:
        return None
    prefix = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="
    if normalized.startswith(prefix):
        masked_key = mask_secret_value(normalized[len(prefix):])
        return f"{prefix}{masked_key}"
    if normalized.startswith("http"):
        if "key=" in normalized:
            base, key = normalized.rsplit("key=", 1)
            return f"{base}key={mask_secret_value(key)}"
        return mask_secret_value(normalized, head=18, tail=8)
    return mask_secret_value(normalized)


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


def warmup_model_targets(config: Dict[str, Any]) -> List[Tuple[str, List[str]]]:
    targets: Dict[str, List[str]] = {}
    for key in ("quick_think_llm", "deep_think_llm"):
        model = str(config.get(key) or "").strip()
        if not model:
            continue
        labels = targets.setdefault(model, [])
        label = _CONFIG_MODEL_LABELS.get(key, key)
        if label not in labels:
            labels.append(label)
    return [(model, labels) for model, labels in targets.items()]


def should_trigger_config_warmup(
    before_cfg: UserRuntimeConfigResponse,
    after_cfg: UserRuntimeConfigResponse,
    updates: UserRuntimeConfigUpdateRequest,
) -> bool:
    if not updates.warmup:
        return False
    if updates.force_warmup:
        return True
    if updates.api_key:
        return True
    before = before_cfg.model_dump()
    after = after_cfg.model_dump()
    return any(before.get(key) != after.get(key) for key in _CONFIG_MODEL_KEYS)


def build_pending_runtime_config(
    updates: UserRuntimeConfigUpdateRequest,
    user_id: str,
    db: Session,
) -> Dict[str, Any]:
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
    if updates.clear_api_key:
        return False
    return bool(updates.api_key)


def probe_runtime_config(config: Dict[str, Any]) -> Dict[str, str]:
    from tradingagents.llm_clients.factory import create_llm_client

    provider = str(config.get("llm_provider") or "openai")
    base_url = config.get("backend_url")
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("quick_think_llm") or config.get("deep_think_llm") or "").strip()

    if not model or not api_key:
        return {"status": "skipped", "reason": "missing_model_or_key"}

    try:
        client = create_llm_client(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=_CONFIG_PROBE_TIMEOUT_SECONDS,
            max_retries=0,
        )
        llm = client.get_llm()
        response = llm.invoke(_CONFIG_PROBE_PROMPT)
        raw = response if isinstance(response, str) else getattr(response, "content", str(response))
        preview = str(raw).strip().replace("\n", " ")[:80] or "<empty>"
        return {"status": "ok", "model": model, "preview": preview}
    except Exception as exc:
        detail = str(exc).strip()
        lowered = detail.lower()
        if "401" in lowered or "invalid authentication" in lowered or "authenticationerror" in lowered:
            raise HTTPException(status_code=400, detail="模型 Key 验证失败：上游返回 401 Invalid Authentication，请检查 API Key 是否正确。") from exc
        raise HTTPException(status_code=400, detail=f"模型连接验证失败：{detail[:200] or 'unknown error'}") from exc


def warmup_runtime_config(
    config: Dict[str, Any],
    prompt: str,
    user_id: str,
    timeout: float = _CONFIG_WARMUP_TIMEOUT_SECONDS,
) -> List[Dict[str, Any]]:
    from tradingagents.llm_clients.factory import create_llm_client

    provider = str(config.get("llm_provider") or "openai")
    base_url = config.get("backend_url")
    api_key = config.get("api_key")
    targets = warmup_model_targets(config)

    if not targets:
        raise HTTPException(status_code=400, detail="请先配置至少一个可用模型。")

    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    for model, labels in targets:
        try:
            client = create_llm_client(
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                max_retries=0,
            )
            llm = client.get_llm()
            response = llm.invoke(prompt)
            raw = response if isinstance(response, str) else getattr(response, "content", str(response))
            content = str(raw).strip() or "<empty>"
            results.append({"model": model, "targets": labels, "content": content, "error": None})
        except Exception as exc:
            detail = str(exc).strip() or "unknown error"
            errors.append(f"{model}: {detail}")
            results.append({"model": model, "targets": labels, "content": None, "error": detail[:200]})

    if not any(item.get("content") for item in results):
        raise HTTPException(status_code=400, detail=f"模型 warmup 失败：{'; '.join(errors)[:300]}")

    return results


def run_config_warmup(config: Dict[str, Any], user_id: str) -> None:
    models = warmup_model_names(config)
    if not models:
        return
    try:
        warmup_runtime_config(config, _CONFIG_WARMUP_PROMPT, user_id, timeout=_CONFIG_WARMUP_TIMEOUT_SECONDS)
    except HTTPException:
        pass


def config_response_for_user(user: Optional[UserDB], db: Session) -> UserRuntimeConfigResponse:
    cfg = build_runtime_config({}, user_id=user.id if user else None, db=db)
    user_cfg = auth_service.get_user_llm_config(db, user.id) if user else None
    webhook_url = auth_service.decrypt_secret(getattr(user_cfg, "wecom_webhook_encrypted", None))
    return UserRuntimeConfigResponse(
        llm_provider=cfg["llm_provider"],
        deep_think_llm=cfg["deep_think_llm"],
        quick_think_llm=cfg["quick_think_llm"],
        backend_url=cfg["backend_url"],
        max_debate_rounds=cfg["max_debate_rounds"],
        max_risk_discuss_rounds=cfg["max_risk_discuss_rounds"],
        has_api_key=bool(user_cfg and user_cfg.api_key_encrypted),
        has_wecom_webhook=bool(webhook_url),
        wecom_webhook_display=mask_wecom_webhook(webhook_url),
        server_fallback_enabled=bool(cfg.get("server_fallback_enabled", True)),
        email_report_enabled=user.email_report_enabled if user and hasattr(user, 'email_report_enabled') else True,
        wecom_report_enabled=user.wecom_report_enabled if user and hasattr(user, "wecom_report_enabled") else True,
        default_analysts=json.loads(user_cfg.default_analysts) if user_cfg and user_cfg.default_analysts else ["market", "social", "news", "fundamentals", "macro", "smart_money", "volume_price"],
    )
