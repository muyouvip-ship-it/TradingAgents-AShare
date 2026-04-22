from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.core.http_utils import get_real_ip
from api.database import UserDB, get_db
from api.deps import require_web_user
from api.schemas.auth import AuthRequestCodeRequest, AuthVerifyCodeRequest, AuthVerifyCodeResponse, UserResponse
from api.services import auth_service

router = APIRouter(prefix="/v1", tags=["Auth"])


@router.post("/auth/request-code")
def request_login_code(request: AuthRequestCodeRequest, db: Session = Depends(get_db)):
    code = auth_service.upsert_login_code(db, request.email)
    dev_code = auth_service.send_login_code(request.email, code)
    return {"message": "验证码已发送", "dev_code": dev_code}


@router.post("/auth/verify-code", response_model=AuthVerifyCodeResponse)
def verify_login_code(
    body: AuthVerifyCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    normalized_email = auth_service.normalize_email(body.email)
    user = auth_service.verify_login_code(
        db,
        normalized_email,
        body.code,
        client_ip=get_real_ip(request),
    )
    if not user:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    response_user = user
    if normalized_email.endswith("@test.com"):
        now = datetime.now(timezone.utc)
        local, domain = normalized_email.split("@", 1)
        isolated_user = UserDB(
            id=str(uuid4()),
            email=f"{local}+{uuid4().hex[:8]}@{domain}",
            is_active=True,
            created_at=now,
            updated_at=now,
            last_login_at=now,
            last_login_ip=get_real_ip(request),
        )
        db.add(isolated_user)
        db.commit()
        db.refresh(isolated_user)
        response_user = isolated_user
    return {
        "access_token": auth_service.create_access_token(response_user),
        "token_type": "bearer",
        "user": UserResponse.model_validate(response_user),
    }


@router.get("/auth/me", response_model=UserResponse)
def get_me(current_user=Depends(require_web_user)):
    return current_user
