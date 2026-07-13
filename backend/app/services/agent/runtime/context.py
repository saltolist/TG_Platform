"""Runtime context — non-serializable dependencies resolved per node."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import User
from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_tools import AgentState


@dataclass
class RuntimeContext:
    """Holds DB session factory, user, provider specs — never checkpointed."""

    session_factory: async_sessionmaker[AsyncSession]
    user_id: uuid.UUID
    user: User | None
    tenant_key: str | None
    settings: Settings
    embedding_backend: EmbeddingBackend
    scope: str
    post_data: dict[str, Any] | None
    ai_profile: dict[str, Any]
    reasoner_spec: ProviderSpec | None = None
    reasoner_model: str = ""
    reasoner_api_key: str = ""
    min_similarity: float = 0.38
    search_k: int = 4
    scope_bias: float = 0.04
    agent_tool_state: AgentState | None = None
    emit_event: Callable[..., Any] | None = None
    audit: Callable[..., Any] | None = None

    def bind_agent_state(self, session: AsyncSession) -> AgentState:
        if self.agent_tool_state is not None:
            self.agent_tool_state.session = session
            return self.agent_tool_state
        self.agent_tool_state = AgentState(
            session=session,
            user_id=self.user_id,
            scope=self.scope,
            tenant_key=self.tenant_key,
            embedding_backend=self.embedding_backend,
            base_post_data=self.post_data,
            min_similarity=self.min_similarity,
            search_k=self.search_k,
            ai_profile=self.ai_profile,
            user=self.user,
            settings=self.settings,
            scope_bias=self.scope_bias,
        )
        return self.agent_tool_state
