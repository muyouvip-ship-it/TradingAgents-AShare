from __future__ import annotations

import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.core.http_utils import get_real_ip
from api.database import UserDB, get_db, get_db_ctx
from api.deps import require_web_user
from api.schemas.auth import (
    AuthRequestCodeRequest,
    AuthVerifyCodeRequest,
    AuthVerifyCodeResponse,
    UserResponse,
    UserTokenCreateRequest,
    UserTokenListItem,
    UserTokenResponse,
)
from api.services import auth_service, token_service

router = APIRouter(prefix="/v1", tags=["Auth"])


@router.post("/auth/request-code")
def request_login_code(request: AuthRequestCodeRequest):
    email = auth_service.normalize_email(request.email)
    if not re.match(r"^[^@\s]+@[^@\s.]+\.[^@\s.]+$", email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    with get_db_ctx() as db:
        code = auth_service.upsert_login_code(db, email)
    dev_code = auth_service.send_login_code(email, code)
    response = {"message": "验证码已发送"}
    if dev_code:
        response["dev_code"] = dev_code
    return response


@router.post("/auth/verify-code", response_model=AuthVerifyCodeResponse)
def verify_login_code(body: AuthVerifyCodeRequest, request: Request, db: Session = Depends(get_db)):
    user = auth_service.verify_login_code(db, body.email, body.code, client_ip=get_real_ip(request))
    if not user:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    access_token = auth_service.create_access_token(user)
    return AuthVerifyCodeResponse(access_token=access_token, user=user)


@router.get("/auth/me", response_model=UserResponse)
def get_me(current_user: UserDB = Depends(require_web_user)):
    return current_user


@router.get("/tokens", response_model=List[UserTokenListItem])
def list_tokens(db: Session = Depends(get_db), current_user: UserDB = Depends(require_web_user)):
    return token_service.list_user_tokens(db, current_user.id)


@router.post("/tokens", response_model=UserTokenResponse)
def create_token(request: UserTokenCreateRequest, db: Session = Depends(get_db), current_user: UserDB = Depends(require_web_user)):
    try:
        return token_service.create_token(db, current_user.id, request.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/tokens/{token_id}")
def delete_token(token_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_web_user)):
    success = token_service.delete_token(db, current_user.id, token_id)
    if not success:
        raise HTTPException(status_code=404, detail="Token 不存在")
    return {"message": "Token 已吊销"}
