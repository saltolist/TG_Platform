from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select

from app.core.auth_cookies import clear_auth_cookie, set_auth_cookie
from app.core.config import settings
from app.core.constants import DEMO_EMAIL
from app.core.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import EmailCode, Profile, User
from app.schemas.auth import (
    AuthSession,
    ForgotPasswordResetDto,
    ForgotPasswordSendCodeDto,
    LoginDto,
    RegisterSendCodeDto,
    RegisterVerifyDto,
)
from app.services.email import generate_code, send_code
from app.services.profile_defaults import empty_profile_payload

router = APIRouter(prefix="/auth", tags=["Auth"])


def _session_for(user: User) -> AuthSession:
    return AuthSession(
        accountId=str(user.id),
        email=user.email,
        createdAt=user.created_at.isoformat(),
    )


def _issue_session(user: User, response: Response) -> AuthSession:
    token = create_access_token(str(user.id))
    set_auth_cookie(response, token)
    return _session_for(user)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _store_code(session: DbSession, email: str, purpose: str, password_hash: str | None) -> str:
    await session.execute(
        delete(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose)
    )
    code = generate_code()
    session.add(
        EmailCode(
            email=email,
            purpose=purpose,
            code=code,
            password_hash=password_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.email_code_ttl_minutes),
        )
    )
    await session.commit()
    return code


async def _consume_code(session: DbSession, email: str, purpose: str, code: str) -> EmailCode:
    result = await session.execute(
        select(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=400, detail="Сначала запросите код на почту")
    if record.expires_at < datetime.now(timezone.utc):
        await session.delete(record)
        await session.commit()
        raise HTTPException(status_code=400, detail="Код истёк, запросите новый")
    if record.code != code.strip():
        raise HTTPException(status_code=400, detail="Неверный код")
    return record


@router.get("/me/", response_model=AuthSession)
async def me(user: CurrentUser) -> AuthSession:
    return _session_for(user)


@router.post("/login/", response_model=AuthSession)
async def login(dto: LoginDto, session: DbSession, response: Response) -> AuthSession:
    email = _normalize_email(dto.email)
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(dto.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    if user.is_seed and email != _normalize_email(DEMO_EMAIL):
        raise HTTPException(status_code=403, detail="Этот аккаунт недоступен для входа")
    return _issue_session(user, response)


@router.post("/logout/", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> Response:
    # Must mutate and return the SAME response object FastAPI injected — returning
    # a brand-new Response() here would discard the Set-Cookie deletion header.
    clear_auth_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/register/send-code/", status_code=status.HTTP_204_NO_CONTENT)
async def register_send_code(dto: RegisterSendCodeDto, session: DbSession) -> Response:
    email = _normalize_email(dto.email)
    if not dto.password.strip():
        raise HTTPException(status_code=400, detail="Укажите email и пароль")

    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    code = await _store_code(session, email, "register", hash_password(dto.password))
    send_code(email, code, "register")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/register/verify/", response_model=AuthSession)
async def register_verify(
    dto: RegisterVerifyDto, session: DbSession, response: Response
) -> AuthSession:
    email = _normalize_email(dto.email)
    record = await _consume_code(session, email, "register", dto.code)

    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    user = User(email=email, password_hash=record.password_hash or "")
    session.add(user)
    await session.flush()
    defaults = empty_profile_payload()
    session.add(
        Profile(
            user_id=user.id,
            channel=defaults["channel"],
            ai=defaults["ai"],
            telegram=defaults["telegram"],
        )
    )
    await session.delete(record)
    await session.commit()
    await session.refresh(user)
    return _issue_session(user, response)


@router.post("/forgot-password/send-code/", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password_send_code(
    dto: ForgotPasswordSendCodeDto, session: DbSession
) -> Response:
    email = _normalize_email(dto.email)
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    # Do not leak whether the email exists; only send a code if it does.
    if user is not None and (not user.is_seed or email == _normalize_email(DEMO_EMAIL)):
        code = await _store_code(session, email, "reset", None)
        send_code(email, code, "reset")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/forgot-password/reset/", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password_reset(dto: ForgotPasswordResetDto, session: DbSession) -> Response:
    email = _normalize_email(dto.email)
    if not dto.password.strip():
        raise HTTPException(status_code=400, detail="Укажите новый пароль")

    record = await _consume_code(session, email, "reset", dto.code)
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    if user.is_seed and email != _normalize_email(DEMO_EMAIL):
        raise HTTPException(status_code=400, detail="Этот аккаунт недоступен для входа")

    user.password_hash = hash_password(dto.password)
    await session.delete(record)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
