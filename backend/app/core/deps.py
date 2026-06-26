import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PRESENTATION_EMAIL
from app.core.guest_tokens import is_guest_token
from app.core.security import decode_token
from app.core.tenant import resolve_tenant_key
from app.db.models import User
from app.db.session import get_session


async def _resolve_presentation_user(session: AsyncSession) -> User:
    result = await session.execute(
        select(User).where(User.email == PRESENTATION_EMAIL, User.is_seed.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.split(" ", 1)[1].strip()

    if is_guest_token(token):
        return await _resolve_presentation_user(session)

    subject = decode_token(token)
    if not subject:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


async def require_writer(user: User = Depends(get_current_user)) -> User:
    if user.is_seed:
        raise HTTPException(status_code=403, detail="Read-only account")
    return user


async def get_tenant_key(
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_session: Annotated[str | None, Header(alias="X-Tenant-Session")] = None,
) -> str | None:
    return resolve_tenant_key(authorization, x_tenant_session)


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentWriter = Annotated[User, Depends(require_writer)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
TenantKey = Annotated[str | None, Depends(get_tenant_key)]
