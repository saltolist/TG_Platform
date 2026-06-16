import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.models import EmailCode, GlobalChat, GlobalNote, Post, Profile, User
from app.db.session import SessionLocal
from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    subprocess.run(["alembic", "upgrade", "head"], check=True, cwd=BACKEND_ROOT)


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session
        await session.execute(delete(Post))
        await session.execute(delete(GlobalChat))
        await session.execute(delete(GlobalNote))
        await session.execute(delete(Profile))
        await session.execute(delete(EmailCode))
        await session.execute(delete(User))
        await session.commit()
