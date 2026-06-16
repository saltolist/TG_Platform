from pydantic import BaseModel, EmailStr


class AuthSession(BaseModel):
    token: str
    accountId: str
    email: str
    createdAt: str


class LoginDto(BaseModel):
    email: EmailStr
    password: str


class RegisterSendCodeDto(BaseModel):
    email: EmailStr
    password: str


class RegisterVerifyDto(BaseModel):
    email: EmailStr
    code: str


class ForgotPasswordSendCodeDto(BaseModel):
    email: EmailStr


class ForgotPasswordResetDto(BaseModel):
    email: EmailStr
    code: str
    password: str
