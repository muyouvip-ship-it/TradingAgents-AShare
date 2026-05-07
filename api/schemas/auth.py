from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_serializer

from api.core.datetime_utils import serialize_datetime_utc


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: Optional[object] = None
    last_login_at: Optional[object] = None
    email_report_enabled: bool = True

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "last_login_at", when_used="json")
    def serialize_user_datetimes(self, value):
        return serialize_datetime_utc(value)


class AuthRequestCodeRequest(BaseModel):
    email: str


class AuthVerifyCodeRequest(BaseModel):
    email: str
    code: str


class AuthVerifyCodeResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserTokenCreateRequest(BaseModel):
    name: str


class UserTokenResponse(BaseModel):
    id: str
    name: str
    token: str
    token_hint: Optional[str] = None
    last_used_at: Optional[object] = None
    created_at: object

    model_config = {"from_attributes": True}

    @field_serializer("last_used_at", "created_at", when_used="json")
    def serialize_token_datetimes(self, value):
        return serialize_datetime_utc(value)


class UserTokenListItem(BaseModel):
    id: str
    name: str
    token_hint: Optional[str] = None
    last_used_at: Optional[object] = None
    created_at: object

    model_config = {"from_attributes": True}

    @field_serializer("last_used_at", "created_at", when_used="json")
    def serialize_token_list_datetimes(self, value):
        return serialize_datetime_utc(value)
