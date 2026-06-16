import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PRESENTATION_EMAIL, PRESENTATION_GUEST_TOKEN
from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_session


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.split(" ", 1)[1].strip()

    if token == PRESENTATION_GUEST_TOKEN:
        result = await session.execute(
            select(User).where(User.email == PRESENTATION_EMAIL, User.is_seed.is_(True))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user

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


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentWriter = Annotated[User, Depends(require_writer)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
