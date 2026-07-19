import os
import uuid
from urllib.parse import urlparse

# Keep pytest deterministic even when host `.env` contains real provider keys or
# enables experimental paths. Individual tests still override these explicitly.
os.environ.update(
    {
        "AI_CONTEXT_STAMPS": "0",
        "OPENAI_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "TAVILY_API_KEY": "",
        "PERPLEXITY_API_KEY": "",
        "RAG_MODE": "off",
        "RAG_TIER_B_ENABLED": "0",
        "AGENT_ACTIONS_ENABLED": "0",
        "AGENT_MEDIA_ENABLED": "0",
        "AGENT_TURN_CONTRACT_V2_ENABLED": "0",
    }
)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.constants import PRESENTATION_EMAIL, PRESENTATION_GUEST_TOKEN
from app.core.security import create_access_token, hash_password
from app.db.models import (
    ActionProposal,
    AgentAuditEvent,
    AgentEvent,
    AgentRun,
    DialogEvidenceTurn,
    EmailCode,
    GlobalChat,
    GlobalNote,
    MediaAsset,
    MediaJob,
    Post,
    Profile,
    User,
)
from app.db.session import get_session
from app.core.config import get_settings

get_settings.cache_clear()
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
def _shim_answer_stream_to_complete(request):
    """answer_node streams the reply via stream_chat_completion_tokens now, not
    the single-shot complete_chat_completion. Agent tests still mock the
    single-shot call (answer JSON as the last side_effect entry). Rather than
    rewrite every one, delegate the token stream to whatever
    complete_chat_completion resolves to at call time and yield its result as a
    single token — preserving the existing mock lists and call order.

    Real streaming granularity is covered directly by test_answer_stream.py
    (pure extractor) and a dedicated answer_node streaming test. test_llm.py
    exercises the real stream_chat_completion_tokens, so it opts out."""
    if "test_llm" in str(request.node.fspath):
        yield
        return
    from unittest.mock import patch as _patch

    from app.services.ai import llm as _llm

    async def _fake_stream(**kwargs):
        # temperature/max_tokens/client are stream-only kwargs; the single-shot
        # signature doesn't take a client, so drop them before delegating.
        kwargs.pop("temperature", None)
        kwargs.pop("max_tokens", None)
        kwargs.pop("client", None)
        yield await _llm.complete_chat_completion(**kwargs)

    with _patch("app.services.ai.llm.stream_chat_completion_tokens", _fake_stream):
        yield


@pytest.fixture(autouse=True)
async def _clean_db() -> None:
    yield
    async with TestSessionLocal() as session:
        from sqlalchemy import text

        for table in (
            "agent_audit_events",
            "media_assets",
            "media_jobs",
            "action_proposals",
            "agent_batch_items",
            "agent_batch_jobs",
            "agent_events",
            "agent_runs",
            "ai_model_usage_events",
            "embedding_jobs",
            "note_embeddings",
            "tenant_overlay_notes",
        ):
            try:
                await session.execute(text(f"DELETE FROM {table}"))
            except Exception:
                await session.rollback()
        await session.execute(delete(DialogEvidenceTurn))
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
