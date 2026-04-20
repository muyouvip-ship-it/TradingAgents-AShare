from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.database import UserDB, get_db_ctx
from api.services import auth_service, token_service

_auth_scheme = HTTPBearer(auto_error=False)


class RequireUser:
    def __init__(self, allow_api_token: bool = True):
        self.allow_api_token = allow_api_token

    def __call__(self, credentials: Optional[HTTPAuthorizationCredentials] = Depends(_auth_scheme)) -> UserDB:
        if not credentials:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
        token = credentials.credentials
        with get_db_ctx() as db:
            try:
                payload = auth_service.decode_access_token(token)
                user_id = str(payload.get("sub") or "")
                user = auth_service.get_user_by_id(db, user_id)
                if user and user.is_active:
                    return user
            except Exception:
                pass
            if self.allow_api_token and token.startswith(token_service.TOKEN_PREFIX):
                user = token_service.verify_token(db, token)
                if user and user.is_active:
                    return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="身份验证失败")


require_api_user = RequireUser(allow_api_token=True)
require_web_user = RequireUser(allow_api_token=False)
