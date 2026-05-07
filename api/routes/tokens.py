from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_web_user
from api.schemas.auth import UserTokenCreateRequest, UserTokenListItem, UserTokenResponse
from api.services import token_service

router = APIRouter(prefix="/v1/tokens", tags=["Tokens"])


@router.get("", response_model=list[UserTokenListItem])
def list_tokens(
    db: Session = Depends(get_db),
    current_user=Depends(require_web_user),
):
    return token_service.list_user_tokens(db, current_user.id)


@router.post("", response_model=UserTokenResponse)
def create_token(
    payload: UserTokenCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_web_user),
):
    token_name = payload.name.strip()
    if not token_name:
        raise HTTPException(status_code=400, detail="Token 名称不能为空")
    try:
        created = token_service.create_token(db, current_user.id, token_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserTokenResponse.model_validate(created)


@router.delete("/{token_id}")
def delete_token(
    token_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_web_user),
):
    deleted = token_service.delete_token(db, current_user.id, token_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Token 不存在")
    return {"message": "Token 已吊销"}
