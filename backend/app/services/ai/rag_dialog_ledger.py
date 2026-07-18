"""Dialog Evidence Ledger for multi-turn RAG referents (ADR-009)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DialogEvidenceTurn
from app.services.ai.rag import _post_title_from_text

if TYPE_CHECKING:
    from app.services.ai.rag_tools import AgentState

LEDGER_SCHEMA_VERSION = 2
_MAX_TURNS = 10
_MAX_ENTITIES = 50

_NOTE_PATH_RE = re.compile(r"/note/(?:post/([\w-]+)/|global/)([\w-]+)/")

# Markers that a follow-up points at the SAME instances discussed in prior turns
# ("эта заметка", "неё", "из них") rather than introducing a new predicate over
# the whole category ("а сколько с изображениями?"). Referential → reuse/narrow
# to ledger entities. New-predicate → ledger sets the topic but must not narrow
# the search to just the discussed instances (chat 63dfb9e4: "сколько заметок
# про систему" narrowed a follow-up "а сколько с изображениями?" down to the 2
# notes already opened, answering "0" instead of counting across all notes).
#
# Deliberately excludes content words like "картинка"/"файл" — those name a
# NEW predicate ("сколько с картинками?"), not a same-instance reference, and
# including them was exactly the chat 63dfb9e4 failure mode. Only
# demonstrative/anaphoric markers belong here.
_REFERENTIAL_MARKERS = (
    "это",
    "та ",
    "тот ",
    "ту ",
    "той ",
    "них",
    "нём",
    "ней",
    "неё",
    "него",
    "предыдущ",
    "этот",
    "эти",
    "эту",
    "этих",
    "выше",
    "которы",
)


def is_referential(user_text: str) -> bool:
    """Heuristic: does user_text point at specific already-discussed entities?

    Deliberately NOT keyed on question type (count/list/etc) — a "сколько"
    question can be either referential ("сколько там файлов?" = in that note)
    or category-wide ("сколько всего заметок с картинками?" = across
    workspace). Only demonstrative/anaphoric markers narrow scope — content
    words like "картинка"/"файл" name a predicate, not a same-instance
    reference, so they must NOT be in this list (see _REFERENTIAL_MARKERS).
    """
    lowered = (user_text or "").lower()
    return any(marker in lowered for marker in _REFERENTIAL_MARKERS)


@dataclass(frozen=True)
class DialogEntityRef:
    entity_type: str
    ref: str | None = None
    post_id: str | None = None
    note_id: str | None = None
    title: str | None = None
    vision_preview: str | None = None
    hydrated: bool = False


@dataclass(frozen=True)
class LedgerEntity:
    entity_type: str
    ref: str | None = None
    post_id: str | None = None
    note_id: str | None = None
    title: str | None = None
    mime: str | None = None
    filename: str | None = None
    vision_preview: str | None = None
    hydrated: bool = False
    # Full user-visible artifact (for example a generated post draft). Stored
    # in JSONB so follow-up turns do not depend on the 400-character transcript
    # snippet used for conversational context.
    content: str | None = None


@dataclass(frozen=True)
class TurnSnapshot:
    turn_id: str
    recorded_at: str
    user_text: str
    target_post_id: str | None
    target_evidence_gap: str | None
    entities: tuple[LedgerEntity, ...]


def chat_ledger_key(*, scope: str, chat_id: str | None, post_id: str | None = None) -> str | None:
    cid = str(chat_id or "").strip()
    if not cid:
        return None
    if scope == "post":
        pid = str(post_id or "").strip()
        if pid:
            return f"post:{pid}:{cid}"
    return f"global:{cid}"


def ledger_chat_id(*, scope: str, chat_id: str | None, post_chat_id: str | None) -> str | None:
    if scope == "post":
        return str(post_chat_id or "").strip() or None
    return str(chat_id or "").strip() or None


def _entity_to_dict(entity: LedgerEntity) -> dict[str, Any]:
    return {
        "entity_type": entity.entity_type,
        "ref": entity.ref,
        "post_id": entity.post_id,
        "note_id": entity.note_id,
        "title": entity.title,
        "mime": entity.mime,
        "filename": entity.filename,
        "vision_preview": entity.vision_preview,
        "hydrated": entity.hydrated,
        "content": entity.content,
    }


def _entity_from_dict(raw: Mapping[str, Any]) -> LedgerEntity:
    return LedgerEntity(
        entity_type=str(raw.get("entity_type") or ""),
        ref=raw.get("ref"),
        post_id=raw.get("post_id"),
        note_id=raw.get("note_id"),
        title=raw.get("title"),
        mime=raw.get("mime"),
        filename=raw.get("filename"),
        vision_preview=raw.get("vision_preview"),
        hydrated=bool(raw.get("hydrated")),
        content=str(raw.get("content") or "") or None,
    )


def _parse_recorded_at(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_to_snapshot(row: DialogEvidenceTurn) -> TurnSnapshot:
    entities_raw = row.entities if isinstance(row.entities, list) else []
    return TurnSnapshot(
        turn_id=str(row.id),
        recorded_at=row.recorded_at.isoformat(),
        user_text=row.user_text,
        target_post_id=row.target_post_id,
        target_evidence_gap=row.target_evidence_gap,
        entities=tuple(_entity_from_dict(item) for item in entities_raw),
    )


async def load_ledger(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    chat_key: str | None,
) -> tuple[TurnSnapshot, ...]:
    if not chat_key:
        return ()
    stmt = (
        select(DialogEvidenceTurn)
        .where(
            DialogEvidenceTurn.user_id == user_id,
            DialogEvidenceTurn.ledger_key == chat_key,
        )
        .order_by(DialogEvidenceTurn.recorded_at.desc())
        .limit(_MAX_TURNS)
    )
    rows = (await session.scalars(stmt)).all()
    return tuple(_row_to_snapshot(row) for row in reversed(rows))


async def append_turn(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    chat_key: str | None,
    snapshot: TurnSnapshot,
) -> None:
    if not chat_key:
        return
    turn_id = uuid.UUID(str(snapshot.turn_id))
    if await session.get(DialogEvidenceTurn, turn_id) is not None:
        return
    row = DialogEvidenceTurn(
        id=turn_id,
        user_id=user_id,
        ledger_key=chat_key,
        recorded_at=_parse_recorded_at(snapshot.recorded_at),
        user_text=snapshot.user_text,
        target_post_id=snapshot.target_post_id,
        target_evidence_gap=snapshot.target_evidence_gap,
        entities=[_entity_to_dict(entity) for entity in snapshot.entities],
    )
    session.add(row)
    await session.flush()

    stale_ids = (
        await session.scalars(
            select(DialogEvidenceTurn.id)
            .where(
                DialogEvidenceTurn.user_id == user_id,
                DialogEvidenceTurn.ledger_key == chat_key,
            )
            .order_by(DialogEvidenceTurn.recorded_at.desc())
            .offset(_MAX_TURNS)
        )
    ).all()
    if stale_ids:
        await session.execute(
            delete(DialogEvidenceTurn).where(DialogEvidenceTurn.id.in_(stale_ids))
        )
        await session.flush()


async def clear_ledger(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    chat_key: str | None,
) -> None:
    """Test helper — reset persisted ledger for a chat key."""
    if not chat_key:
        return
    await session.execute(
        delete(DialogEvidenceTurn).where(
            DialogEvidenceTurn.user_id == user_id,
            DialogEvidenceTurn.ledger_key == chat_key,
        )
    )
    await session.flush()


def ledger_hydrated_attachments(ledger: tuple[TurnSnapshot, ...]) -> tuple[LedgerEntity, ...]:
    entities: list[LedgerEntity] = []
    seen: set[str] = set()
    for turn in ledger:
        for entity in turn.entities:
            if entity.entity_type != "attachment" or not entity.ref:
                continue
            if not entity.hydrated:
                continue
            if entity.ref in seen:
                continue
            seen.add(entity.ref)
            entities.append(entity)
    return tuple(entities)


def _is_attachment_hydrated(state: AgentState, ref: str) -> bool:
    return (
        f"hydrate:vision:{ref}" in state.visited
        or f"hydrate:{ref}" in state.visited
    )


def _vision_preview_for_ref(state: AgentState, ref: str) -> str | None:
    file_id = ref.split(":", 1)[1] if ref.startswith("attachment:") else ref
    for cite, plain in state.context_blocks:
        path = str(getattr(cite, "path", "") or "")
        if file_id and file_id in path:
            text = (plain or "").strip()
            if text:
                return text[:400] + ("…" if len(text) > 400 else "")
    return None


def _attachment_meta_from_context(
    state: AgentState,
    ref: str,
) -> tuple[str | None, str | None, str | None]:
    file_id = ref.split(":", 1)[1] if ref.startswith("attachment:") else ref
    post_id: str | None = None
    note_id: str | None = None
    filename: str | None = None
    for cite, _plain in state.context_blocks:
        path = str(getattr(cite, "path", "") or "")
        if not file_id or file_id not in path:
            continue
        filename = str(getattr(cite, "title", "") or "").strip() or None
        match = _NOTE_PATH_RE.search(path)
        if match:
            post_id = match.group(1) or post_id
            note_id = match.group(2) or note_id
        break
    return post_id, note_id, filename


def build_snapshot_from_agent_state(state: AgentState, *, user_text: str) -> TurnSnapshot:
    entities: list[LedgerEntity] = []
    seen_keys: set[str] = set()

    def _add(entity: LedgerEntity) -> None:
        key = entity.ref or f"{entity.entity_type}:{entity.post_id}:{entity.note_id}"
        if key in seen_keys:
            return
        seen_keys.add(key)
        entities.append(entity)

    target_id = str(state.resolved_target_post_id or "").strip() or None
    for post_id, post_data in state.opened_posts.items():
        pid = str(post_id or "").strip()
        if not pid:
            continue
        text_value = str(post_data.get("text") or "").strip()
        title = _post_title_from_text(text_value) if text_value else f"Пост {pid}"
        _add(
            LedgerEntity(
                entity_type="post",
                post_id=pid,
                title=title,
            )
        )

    for visit_ref in state.visited:
        if visit_ref.startswith("note:") and ":attachments" not in visit_ref:
            note_id = visit_ref[len("note:") :].strip()
            if note_id:
                _add(
                    LedgerEntity(
                        entity_type="note",
                        note_id=note_id,
                        post_id=target_id,
                    )
                )

    attachment_refs: list[str] = list(state.listed_image_attachment_refs)
    for visit_ref in state.visited:
        if visit_ref.startswith("hydrate:vision:"):
            attachment_refs.append(visit_ref[len("hydrate:vision:") :].strip())
        elif visit_ref.startswith("hydrate:attachment:"):
            attachment_refs.append(visit_ref[len("hydrate:") :].strip())

    for ref in attachment_refs:
        ref = str(ref or "").strip()
        if not ref.startswith("attachment:"):
            continue
        post_id, note_id, filename = _attachment_meta_from_context(state, ref)
        if not post_id:
            post_id = target_id
        _add(
            LedgerEntity(
                entity_type="attachment",
                ref=ref,
                post_id=post_id,
                note_id=note_id,
                filename=filename,
                vision_preview=_vision_preview_for_ref(state, ref),
                hydrated=_is_attachment_hydrated(state, ref),
            )
        )

    if len(entities) > _MAX_ENTITIES:
        entities = entities[-_MAX_ENTITIES:]

    return TurnSnapshot(
        turn_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc).isoformat(),
        user_text=(user_text or "").strip(),
        target_post_id=target_id,
        target_evidence_gap=state.target_evidence_gap,
        entities=tuple(entities),
    )


def build_snapshot_from_evidence_records(
    *,
    user_text: str,
    evidence_ids: list[str],
    records: dict[str, dict],
    target_post_id: str | None = None,
    answer_text: str = "",
    artifact_kind: str | None = None,
    turn_id: str | None = None,
) -> TurnSnapshot:
    """Ledger turn from EvidenceRecord dicts (ADR-012 schema v2)."""
    entities: list[LedgerEntity] = []
    for eid in evidence_ids:
        rec = records.get(eid) or {}
        path = str(rec.get("citation_path") or rec.get("source_ref") or "")
        kind = str(rec.get("kind") or "")
        if kind in {"note_chunk", "attachment_text"} and "/note/" in path:
            match = _NOTE_PATH_RE.search(path)
            note_id = match.group(2) if match else None
            post_id = (match.group(1) if match else None) or target_post_id
            if note_id:
                entities.append(
                    LedgerEntity(
                        entity_type="note",
                        note_id=note_id,
                        post_id=post_id,
                        title=str(rec.get("citation_title") or "") or None,
                    )
                )
        elif kind == "post_text":
            path_parts = [part for part in path.split("/") if part]
            post_id = path_parts[1] if len(path_parts) >= 2 and path_parts[0] == "post" else target_post_id
            entities.append(
                LedgerEntity(
                    entity_type="post",
                    post_id=post_id,
                    title=rec.get("citation_title"),
                )
            )
    artifact = (answer_text or "").strip()
    if artifact:
        entities.append(
            LedgerEntity(
                entity_type=artifact_kind or "assistant_artifact",
                title=artifact_kind or "assistant answer",
                content=artifact[:12000],
            )
        )
    return TurnSnapshot(
        turn_id=turn_id or str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc).isoformat(),
        user_text=(user_text or "").strip(),
        target_post_id=target_post_id,
        target_evidence_gap=None,
        entities=tuple(entities),
    )


def format_ledger_for_planner(
    ledger: tuple[TurnSnapshot, ...],
    *,
    last_n: int = 3,
) -> str:
    if not ledger:
        return "(dialog evidence ledger пуст — нет prior hydrated turns)"
    lines = ["Dialog evidence ledger (prior turns, strong entries only):"]
    for turn in ledger[-last_n:]:
        lines.append(f"- turn user_text={turn.user_text[:120]!r}")
        if turn.target_post_id:
            lines.append(f"  target_post_id={turn.target_post_id!r}")
        for entity in turn.entities:
            if entity.entity_type == "post":
                lines.append(
                    f"  post id={entity.post_id!r} title={entity.title!r}"
                )
            elif entity.entity_type == "note":
                lines.append(
                    f"  note id={entity.note_id!r} post_id={entity.post_id!r}"
                )
            elif entity.entity_type == "attachment":
                preview = entity.vision_preview or "—"
                if len(preview) > 120:
                    preview = preview[:119] + "…"
                lines.append(
                    f"  attachment ref={entity.ref!r} hydrated={entity.hydrated} "
                    f"post_id={entity.post_id!r} note_id={entity.note_id!r} "
                    f"filename={entity.filename!r} vision_preview={preview!r}"
                )
            elif entity.content:
                lines.append(
                    f"  artifact type={entity.entity_type!r} title={entity.title!r}\n"
                    f"    content={entity.content[:6000]!r}"
                )
    return "\n".join(lines)


def ledger_entity_to_ref(entity: LedgerEntity) -> DialogEntityRef:
    return DialogEntityRef(
        entity_type=entity.entity_type,
        ref=entity.ref,
        post_id=entity.post_id,
        note_id=entity.note_id,
        title=entity.title,
        vision_preview=entity.vision_preview,
        hydrated=entity.hydrated,
    )


def flatten_ledger_entities(ledger: tuple[TurnSnapshot, ...]) -> tuple[LedgerEntity, ...]:
    entities: list[LedgerEntity] = []
    seen: set[str] = set()
    for turn in ledger:
        for entity in turn.entities:
            key = entity.ref or f"{entity.entity_type}:{entity.post_id}:{entity.note_id}"
            if key in seen:
                continue
            seen.add(key)
            entities.append(entity)
    return tuple(entities)


def _attachment_cite_path(entity: LedgerEntity) -> str:
    ref = str(entity.ref or "").strip()
    file_id = ref.split(":", 1)[1] if ref.startswith("attachment:") else ref
    note_id = str(entity.note_id or "unknown").strip()
    post_id = str(entity.post_id or "").strip()
    post_part = f"post/{post_id}/" if post_id else "global/"
    return f"/note/{post_part}{note_id}/attachment/{file_id}/"


def seed_hydrated_attachments_from_ledger(
    state: AgentState,
    *,
    user_text: str = "",
    ledger: tuple[TurnSnapshot, ...],
    last_n_turns: int = 3,
) -> tuple[str, ...]:
    """Replay prior-turn hydrated attachment previews into the current agent state."""
    if not ledger:
        return ()

    from app.services.ai.note_citations import NoteCite

    # Wider than is_referential() on purpose: replaying a vision preview is
    # cheap and safe even on a loose match (worst case we add unused context),
    # unlike is_referential() which gates whether the search narrows to fewer
    # instances (a false positive there silently drops real answers).
    deictic = is_referential(user_text) or any(
        marker in (user_text or "").lower()
        for marker in ("картин", "файл", "вложен")
    )
    if not deictic and len(ledger) <= 1:
        return ()

    ledger_entities: dict[str, LedgerEntity] = {}
    for turn in ledger[-last_n_turns:]:
        for entity in turn.entities:
            if entity.entity_type != "attachment" or not entity.ref:
                continue
            if not entity.hydrated or not (entity.vision_preview or "").strip():
                continue
            host_post_id = str(entity.post_id or turn.target_post_id or "").strip() or None
            if host_post_id and not entity.post_id:
                entity = LedgerEntity(
                    entity_type=entity.entity_type,
                    ref=entity.ref,
                    post_id=host_post_id,
                    note_id=entity.note_id,
                    title=entity.title,
                    mime=entity.mime,
                    filename=entity.filename,
                    vision_preview=entity.vision_preview,
                    hydrated=entity.hydrated,
                )
            ledger_entities[entity.ref] = entity

    seeded: list[str] = []
    for ref, entity in ledger_entities.items():
        vision_key = f"hydrate:vision:{ref}"
        if vision_key in state.visited:
            seeded.append(ref)
            continue
        cite = NoteCite(
            path=_attachment_cite_path(entity),
            title=str(entity.filename or ref),
        )
        state.context_blocks.append((cite, str(entity.vision_preview or "").strip()))
        state.visited.add(vision_key)
        state.visited.add(f"hydrate:{ref}")
        if entity.ref and entity.ref not in state.listed_image_attachment_refs:
            state.listed_image_attachment_refs.append(entity.ref)
        host_post_id = str(entity.post_id or "").strip()
        if host_post_id:
            state.opened_posts.setdefault(host_post_id, {"id": host_post_id, "text": ""})
            state.visited.add(f"post:{host_post_id}")
        note_id = str(entity.note_id or "").strip()
        if note_id:
            state.visited.add(f"note:{note_id}")
        seeded.append(ref)
    return tuple(seeded)


def referential_hints_from_ledger(
    user_text: str,
    ledger: tuple[TurnSnapshot, ...],
    *,
    last_n_turns: int = 3,
) -> list[str]:
    """Planner hints to reopen ledger notes/posts directly, skipping SearchNodes.

    Only fires for referential follow-ups ("эта заметка", "неё") — a new-predicate
    follow-up ("а сколько с изображениями?") must NOT be steered toward just the
    discussed instances, so it gets no hints and searches the full category.
    Notes carry no body in the ledger (unlike hydrated attachments), so reuse
    here means "open directly by known note_id", not "skip reading entirely".
    """
    if not ledger or not is_referential(user_text):
        return []

    hints: list[str] = []
    seen_notes: set[str] = set()
    seen_posts: set[str] = set()
    for turn in ledger[-last_n_turns:]:
        for entity in turn.entities:
            if entity.entity_type == "note" and entity.note_id:
                note_id = str(entity.note_id).strip()
                if note_id and note_id not in seen_notes:
                    seen_notes.add(note_id)
                    post_part = f" post_id={entity.post_id}" if entity.post_id else ""
                    hints.append(
                        f"OpenNote note_id={note_id}{post_part} "
                        "(уже открыта в этом диалоге — не ищи через SearchNodes)"
                    )
            elif entity.entity_type == "post" and entity.post_id:
                post_id = str(entity.post_id).strip()
                if post_id and post_id not in seen_posts:
                    seen_posts.add(post_id)
                    hints.append(
                        f"OpenPost post_id={post_id} "
                        "(уже открыт в этом диалоге — не ищи через SearchNodes)"
                    )
    return hints
