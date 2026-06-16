import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.models import EmailCode, GlobalChat, GlobalNote, Post, Profile, User
from app.db.session import get_session
from app.main import app

# Isolated test engine: NullPool avoids stale asyncpg connections across event loops.
test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _override_db_session() -> None:
    async def _get_session():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = _get_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def _clean_db() -> None:
    yield
    async with TestSessionLocal() as session:
        await session.execute(delete(Post))
        await session.execute(delete(GlobalChat))
        await session.execute(delete(GlobalNote))
        await session.execute(delete(Profile))
        await session.execute(delete(EmailCode))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture(scope="session", autouse=True)
async def _dispose_test_engine() -> None:
    yield
    await test_engine.dispose()


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def fetch_email_code(email: str) -> str:
    """Read a one-time code using a short-lived session (avoids fixture teardown conflicts)."""
    async with TestSessionLocal() as session:
        result = await session.execute(select(EmailCode).where(EmailCode.email == email))
        return result.scalar_one().code
