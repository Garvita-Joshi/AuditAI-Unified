from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class OtpRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=200)


class OtpRequestResponse(BaseModel):
    message: str
    expires_in_seconds: int
    development_code: Optional[str] = None


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str]
    role: str
    display_name: str
    employee_id: str
    roles: list[str]

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResponse
