import os
import uuid
from urllib.parse import urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.constants import PRESENTATION_EMAIL, PRESENTATION_GUEST_TOKEN
from app.core.security import create_access_token, hash_password
from app.db.models import EmailCode, GlobalChat, GlobalNote, Post, Profile, User
from app.db.session import get_session
from app.main import app

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://tg:tg@localhost:5432/tg_test"


def _resolve_test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    db_name = urlparse(url.replace("+asyncpg", "")).path.lstrip("/").split("?")[0]
    if db_name == "tg":
        raise RuntimeError(
            "Refusing to run pytest against the dev database 'tg' — it would delete your "
            "registered accounts after each test. Run ./scripts/ensure-test-db.sh from the "
            "repo root, then: TEST_DATABASE_URL=postgresql+asyncpg://tg:tg@localhost:5432/tg_test pytest"
        )
    return url


TEST_DATABASE_URL = _resolve_test_database_url()

# Isolated test engine: NullPool avoids stale asyncpg connections across event loops.
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
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


def guest_auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PRESENTATION_GUEST_TOKEN}"}


@pytest.fixture
async def presentation_user() -> User:
    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == PRESENTATION_EMAIL))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email=PRESENTATION_EMAIL,
                password_hash=hash_password("seed-no-login"),
                is_seed=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


@pytest.fixture
async def writer_user() -> User:
    async with TestSessionLocal() as session:
        user = User(
            email=f"writer-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("SecretPass123"),
            is_seed=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
def writer_auth_headers(writer_user: User) -> dict[str, str]:
    token = create_access_token(str(writer_user.id))
    return {"Authorization": f"Bearer {token}"}


def sample_post(post_id: str, *, text: str = "Contract test post") -> dict:
    return {
        "id": post_id,
        "status": "draft",
        "rubric": None,
        "text": text,
        "notes": [],
        "chats": [],
    }


def sample_global_chat(chat_id: str, *, title: str = "Contract chat") -> dict:
    return {
        "id": chat_id,
        "title": title,
        "preview": "Preview",
        "date": "2026-06-17T10:00:00.000Z",
        "history": [{"role": "user", "text": "Hello"}],
    }


def sample_global_note(note_id: str, *, title: str = "Contract note") -> dict:
    return {
        "id": note_id,
        "title": title,
        "ai": True,
        "date": "2026-06-17T10:00:00.000Z",
        "body": "Note body",
    }
