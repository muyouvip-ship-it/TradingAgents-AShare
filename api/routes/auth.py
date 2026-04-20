from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_web_user
from api.schemas.auth import AuthRequestCodeRequest, AuthVerifyCodeRequest, AuthVerifyCodeResponse, UserResponse

router = APIRouter(prefix="/v1", tags=["Auth"])


@router.post("/auth/request-code")
def request_login_code(request: AuthRequestCodeRequest):
    return {"message": "验证码已发送"}


@router.post("/auth/verify-code", response_model=AuthVerifyCodeResponse)
def verify_login_code(body: AuthVerifyCodeRequest):
    raise HTTPException(status_code=400, detail="验证码错误或已过期")


@router.get("/auth/me", response_model=UserResponse)
def get_me(current_user=Depends(require_web_user)):
    return current_user
