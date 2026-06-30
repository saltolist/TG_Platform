from fastapi import Response

from app.core.config import settings


def set_auth_cookie(response: Response, token: str) -> None:
    domain = settings.cookie_domain.strip() or None
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=domain,
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    domain = settings.cookie_domain.strip() or None
    response.delete_cookie(
        key=settings.jwt_cookie_name,
        domain=domain,
        path="/",
    )
