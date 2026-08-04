from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None
    factory_name_ar: str = Field(min_length=1, max_length=255)
    factory_name_en: str = Field(min_length=1, max_length=255)
    locale: str = "ar"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class UpdateMeRequest(BaseModel):
    """Self-service profile edit. Only supplied fields are changed."""

    full_name: str | None = Field(default=None, max_length=160)
    locale: str | None = Field(default=None, pattern="^(ar|en)$")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: str
    factory_id: uuid.UUID | None
    locale: str

    model_config = {"from_attributes": True}
