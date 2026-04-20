from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import UserDB, get_db
from api.deps import require_web_user
from api.schemas.config import (
    UserRuntimeConfigResponse,
    UserRuntimeConfigUpdateRequest,
    UserRuntimeWarmupRequest,
    UserRuntimeWarmupResponse,
    WecomWebhookWarmupRequest,
    WecomWebhookWarmupResponse,
)
from api.services import auth_service
from api.services.config_service import (
    build_pending_runtime_config,
    config_response_for_user,
    probe_runtime_config,
    run_config_warmup,
    should_probe_runtime_config,
    should_trigger_config_warmup,
    warmup_model_names,
    warmup_runtime_config,
)

router = APIRouter(prefix="/v1", tags=["Config"])


@router.get("/config", response_model=UserRuntimeConfigResponse)
def get_runtime_config(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_web_user),
):
    return config_response_for_user(current_user, db)


@router.patch("/config")
def update_runtime_config(
    updates: UserRuntimeConfigUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_web_user),
):
    normalized_wecom_webhook = None
    if updates.wecom_webhook_url:
        from api.services.wecom_notification_service import normalize_webhook_url

        try:
            normalized_wecom_webhook = normalize_webhook_url(updates.wecom_webhook_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    persistent_user = db.query(UserDB).filter(UserDB.id == current_user.id).first() or current_user
    before_cfg = config_response_for_user(persistent_user, db)
    pending_cfg = build_pending_runtime_config(updates, persistent_user.id, db)
    if should_probe_runtime_config(before_cfg, pending_cfg, updates):
        probe = probe_runtime_config(pending_cfg)
    row = auth_service.upsert_user_llm_config(
        db,
        persistent_user.id,
        llm_provider=updates.llm_provider,
        deep_think_llm=updates.deep_think_llm,
        quick_think_llm=updates.quick_think_llm,
        backend_url=updates.backend_url,
        max_debate_rounds=updates.max_debate_rounds,
        max_risk_discuss_rounds=updates.max_risk_discuss_rounds,
        api_key=updates.api_key,
        wecom_webhook_url=normalized_wecom_webhook,
        clear_api_key=updates.clear_api_key,
        clear_wecom_webhook=updates.clear_wecom_webhook,
        default_analysts=updates.default_analysts,
    )
    user_pref_updated = False
    if updates.email_report_enabled is not None:
        persistent_user.email_report_enabled = updates.email_report_enabled
        user_pref_updated = True
    if updates.wecom_report_enabled is not None:
        persistent_user.wecom_report_enabled = updates.wecom_report_enabled
        user_pref_updated = True
    if user_pref_updated:
        db.commit()
    current_cfg = config_response_for_user(persistent_user, db)
    warmup_models = warmup_model_names(current_cfg.model_dump())
    should_warmup = should_trigger_config_warmup(before_cfg, current_cfg, updates)
    warmup_payload: dict
    if should_warmup and warmup_models:
        warmup_payload = {
            "requested": True,
            "triggered": True,
            "status": "scheduled",
            "models": warmup_models,
            "message": f"模型配置已保存，后台正在预热 {len(warmup_models)} 个模型。",
        }
        background_tasks.add_task(
            run_config_warmup,
            pending_cfg,
            persistent_user.id,
        )
    elif updates.warmup:
        warmup_payload = {
            "requested": True,
            "triggered": False,
            "status": "skipped",
            "models": warmup_models,
            "message": "模型配置已保存，本次未触发 warmup。",
        }
    else:
        warmup_payload = {
            "requested": False,
            "triggered": False,
            "status": "disabled",
            "models": [],
            "message": "模型配置已保存。",
        }
    filtered = {
        k: v
        for k, v in updates.model_dump().items()
        if v is not None
        and k not in {"api_key", "wecom_webhook_url", "warmup", "force_warmup"}
        and (
            k in {"llm_provider", "deep_think_llm", "quick_think_llm", "backend_url", "max_debate_rounds", "max_risk_discuss_rounds"}
            or k in {"email_report_enabled", "wecom_report_enabled"}
            or (k in {"clear_api_key", "clear_wecom_webhook"} and bool(v))
        )
    }
    return {
        "message": "用户配置已更新",
        "applied": filtered,
        "has_api_key": bool(row.api_key_encrypted),
        "current": current_cfg,
        "warmup": warmup_payload,
    }


@router.post("/config/warmup", response_model=UserRuntimeWarmupResponse)
def warmup_runtime_config(
    request: UserRuntimeWarmupRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_web_user),
):
    pending_cfg = build_pending_runtime_config(request, current_user.id, db)
    prompt = (request.prompt or "").strip() or "你好"
    results = warmup_runtime_config(pending_cfg, prompt, current_user.id)
    return {
        "prompt": prompt,
        "results": results,
    }


@router.post("/config/wecom/warmup", response_model=WecomWebhookWarmupResponse)
async def warmup_wecom_webhook(
    request: WecomWebhookWarmupRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_web_user),
):
    from api.services.wecom_notification_service import build_test_message, normalize_webhook_url, send_message

    webhook_url = (request.wecom_webhook_url or "").strip()
    if not webhook_url:
        user_cfg = auth_service.get_user_llm_config(db, current_user.id)
        webhook_url = auth_service.decrypt_secret(getattr(user_cfg, "wecom_webhook_encrypted", None)) or ""
    if not webhook_url:
        raise HTTPException(status_code=400, detail="请先填写或保存企业微信 Webhook")
    try:
        webhook_url = normalize_webhook_url(webhook_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        sent = await asyncio.to_thread(send_message, build_test_message(request.content), webhook_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook 测试发送失败：{exc}") from exc
    if not sent:
        raise HTTPException(status_code=400, detail="Webhook 测试发送失败，请检查地址或机器人状态")

    return {
        "sent": True,
        "message": "Webhook 测试发送成功",
        "webhook_display": webhook_url,
    }
