import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.models import EmailCode, GlobalChat, GlobalNote, Post, Profile, User
from app.db.session import SessionLocal, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
async def _engine_lifecycle() -> None:
    """Keep a single event loop for the global async engine (pytest-asyncio session scope)."""
    yield
    await engine.dispose()


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
