"""Durable, message-level provenance for agent answers.

The evidence pack is an input to generation.  A message context manifest is the
smaller, user-facing contract that records what actually supported the answer,
which targets were operated on, and which derived artifacts can be opened in a
later turn.  Keeping this conversion deterministic prevents retrieval catalogs
and semantic cards from being rendered as if they were workspace objects.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

MESSAGE_CONTEXT_SCHEMA = "workspace.message-context/v1"
REFERENT_RESOLUTION_SCHEMA = "workspace.referent-resolution/v1"


class _ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ConsideredContext(_ManifestModel):
    evidence_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    fidelity: str = Field(min_length=1)
    revision: int | None = Field(default=None, ge=0)
    role: str = "context"


class ContextRef(_ManifestModel):
    ref: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    title: str | None = None
    summary: str | None = None
    revision: int | None = Field(default=None, ge=0)
    source_turn_id: str | None = None
    role: str = "claim_support"
    provenance: str = "exact"
    route: str | None = None


class ReferenceSet(_ManifestModel):
    ref: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    ordered_members: tuple[str, ...] = ()
    selected_members: tuple[str, ...] = ()
    selection_mode: str = "all"
    source_turn_id: str | None = None


class ArtifactRef(_ManifestModel):
    ref: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    source_turn_id: str | None = None
    role: str = "derived_output"
    title: str | None = None
    route: str | None = None


class StaleRef(_ManifestModel):
    ref: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    previous_revision: int | None = None
    current_revision: int | None = None


class MessageContextManifest(_ManifestModel):
    manifest_schema: Literal["workspace.message-context/v1"] = Field(
        default=MESSAGE_CONTEXT_SCHEMA, alias="schema"
    )
    message_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    source_turn_id: str = Field(min_length=1)
    considered_context: tuple[ConsideredContext, ...] = ()
    cited_evidence: tuple[str, ...] = ()
    context_refs: tuple[ContextRef, ...] = ()
    reference_sets: tuple[ReferenceSet, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    stale_refs: tuple[StaleRef, ...] = ()
    provenance: str = "exact"


class ReferentResolution(_ManifestModel):
    resolution_schema: Literal["workspace.referent-resolution/v1"] = Field(
        default=REFERENT_RESOLUTION_SCHEMA, alias="schema"
    )
    references: tuple[dict[str, Any], ...] = ()
    unresolved: tuple[str, ...] = ()
    ambiguity: dict[str, Any] | None = None


_POST_PATH_RE = re.compile(r"/post/([^/]+)/")
_NOTE_PATH_RE = re.compile(r"/note/(?:post/([^/]+)/|global/)([^/]+)/")


def _object_ref(record: Mapping[str, Any], evidence_id: str) -> tuple[str, str] | None:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
    source = str(metadata.get("ref") or record.get("source_ref") or record.get("citation_path") or "")
    path = str(record.get("citation_path") or source)
    match = _NOTE_PATH_RE.search(path)
    if match:
        return f"note:{match.group(2)}", "note"
    match = _POST_PATH_RE.search(path)
    if match:
        return f"post:{match.group(1)}", "post"
    if source.startswith("note:"):
        return source, "note"
    if source.startswith("post:"):
        return source, "post"
    # Catalogs and workspace collection paths are provenance only.
    if str(record.get("kind") or "") == "catalog":
        return None
    if evidence_id.startswith(("note:", "post:")):
        kind = evidence_id.split(":", 1)[0]
        return evidence_id, kind
    return None


def _revision(record: Mapping[str, Any]) -> int | None:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    raw = metadata.get("source_revision", metadata.get("revision"))
    if raw is None:
        raw = provenance.get("source_revision", provenance.get("revision"))
    if raw is None:
        raw = record.get("source_revision", record.get("revision"))
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def supplied_object_refs(evidence_pack: Mapping[str, Any] | None) -> set[str]:
    refs: set[str] = set()
    for item in (evidence_pack or {}).get("items") or ():
        if not isinstance(item, Mapping):
            continue
        evidence_id = str(item.get("id") or "")
        resolved = _object_ref(item, evidence_id)
        if resolved is not None:
            refs.add(resolved[0])
        # Catalog membership is discovery/structural evidence, not proof that
        # each member was selected and supplied as object context.
    return refs


def evidence_id_aliases(evidence_pack: Mapping[str, Any] | None) -> dict[str, str]:
    """Map model-friendly object refs to authoritative EvidencePack IDs.

    Only primary object items create aliases. Catalog membership alone is not
    sufficient evidence for a claim about an object's full content.
    """

    aliases: dict[str, str] = {}
    for item in (evidence_pack or {}).get("items") or ():
        if not isinstance(item, Mapping):
            continue
        evidence_id = str(item.get("id") or "")
        if not evidence_id or str(item.get("kind") or "") == "catalog":
            continue
        resolved = _object_ref(item, evidence_id)
        if resolved is not None:
            aliases.setdefault(resolved[0], evidence_id)
    return aliases


def _route(kind: str, ref: str) -> str | None:
    identifier = ref.split(":", 1)[-1]
    if kind == "post":
        return f"/post/{identifier}/"
    if kind == "note":
        return f"/note/global/{identifier}/"
    return None


def _route_for_item(kind: str, ref: str, item: Mapping[str, Any]) -> str | None:
    if kind == "note":
        path = str(item.get("citation_path") or "")
        match = _NOTE_PATH_RE.search(path)
        if match and match.group(1):
            return f"/note/post/{match.group(1)}/{ref.split(':', 1)[-1]}/"
    return _route(kind, ref)


def _display_summary(item: Mapping[str, Any]) -> str | None:
    """Return the bounded semantic card used in cross-turn context.

    EvidencePack content is commonly hydrated to full text before generation;
    it must never silently replace the discovery card in the durable manifest.
    """
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    for key in ("card_text", "preview"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    content = str(item.get("content") or "").strip()
    return content[:240] or None


def _context_ref_from_item(
    *, ref: str, kind: str, item: Mapping[str, Any], source_turn_id: str,
    role: str, provenance: str,
) -> ContextRef:
    return ContextRef(
        ref=ref,
        kind=kind,
        title=str(item.get("title") or "") or None,
        summary=_display_summary(item),
        revision=_revision(item),
        source_turn_id=source_turn_id,
        role=role,
        provenance=provenance,
        route=_route_for_item(kind, ref, item),
    )


def _context_ref_from_member(
    *, member: Mapping[str, Any], source_turn_id: str, role: str, provenance: str,
) -> ContextRef | None:
    kind = str(member.get("kind") or "")
    identifier = str(member.get("id") or "").strip()
    if kind not in {"post", "note"} or not identifier:
        return None
    ref = f"{kind}:{identifier}"
    preview = str(member.get("card_text") or member.get("preview") or "").strip()
    return ContextRef(
        ref=ref,
        kind=kind,
        title=str(member.get("title") or "") or None,
        summary=preview[:240] or None,
        revision=_revision(member),
        source_turn_id=source_turn_id,
        role=role,
        provenance=provenance,
        route=_route(kind, ref),
    )


def artifact_ref(*, answer_text: str, source_turn_id: str, kind: str = "assistant_answer", route_id: str | None = None) -> ArtifactRef | None:
    content = (answer_text or "").strip()
    if not content:
        return None
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ArtifactRef(
        ref=f"artifact:sha256:{digest}",
        kind=kind,
        content_hash=f"sha256:{digest}",
        source_turn_id=source_turn_id,
        title="assistant answer",
        route=f"#message-{route_id or source_turn_id}",
    )


def build_message_context_manifest(
    *,
    message_id: str,
    run_id: str,
    source_turn_id: str,
    evidence_pack: Mapping[str, Any] | None,
    claims: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    used_context_refs: list[str] | tuple[str, ...] = (),
    target_contract: Mapping[str, Any] | None = None,
    answer_text: str = "",
    provenance: str = "exact",
    stale_refs: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
) -> MessageContextManifest:
    """Build a manifest from the verified pack and validated answer output.

    Unsupported claim IDs and context refs are deliberately omitted here; the
    answer validator reports them before this function is called.  This helper
    remains defensive so replaying old snapshots cannot manufacture refs.
    """
    pack = dict(evidence_pack or {})
    pack_items = [item for item in pack.get("items") or () if isinstance(item, Mapping)]
    item_by_id = {str(item.get("id")): item for item in pack_items if str(item.get("id") or "")}
    evidence_ids = {str(item) for item in pack.get("evidence_ids") or ()} | set(item_by_id)
    cited = tuple(dict.fromkeys(
        str(eid) for claim in claims if isinstance(claim, Mapping)
        for eid in claim.get("evidence_ids") or () if str(eid) in evidence_ids
    ))
    considered = tuple(
        ConsideredContext(
            evidence_id=eid,
            kind=str(item.get("kind") or "evidence"),
            fidelity=str(item.get("fidelity") or "full_text"),
            revision=_revision(item),
            role="context",
        )
        for eid, item in item_by_id.items()
    )
    refs: dict[str, ContextRef] = {}
    for eid in cited:
        item = item_by_id.get(eid, {})
        obj = _object_ref(item, eid)
        if obj is None:
            if str(item.get("kind") or "") == "catalog":
                metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
                for member in metadata.get("members") or ():
                    if not isinstance(member, Mapping):
                        continue
                    context_ref = _context_ref_from_member(
                        member=member,
                        source_turn_id=source_turn_id,
                        role="claim_support",
                        provenance=provenance,
                    )
                    if context_ref is not None:
                        refs.setdefault(context_ref.ref, context_ref)
            continue
        ref, kind = obj
        refs.setdefault(ref, _context_ref_from_item(
            ref=ref, kind=kind, item=item, source_turn_id=source_turn_id,
            role="claim_support", provenance=provenance,
        ))
    supplied_refs: dict[str, ContextRef] = {}
    for raw in used_context_refs:
        ref = str(raw).strip()
        if not ref:
            continue
        for eid, item in item_by_id.items():
            obj = _object_ref(item, eid)
            if obj and obj[0] == ref:
                supplied_refs.setdefault(ref, _context_ref_from_item(
                    ref=ref, kind=obj[1], item=item, source_turn_id=source_turn_id,
                    role="used_context", provenance=provenance,
                ))
                continue
            if str(item.get("kind") or "") == "catalog":
                metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
                for member in metadata.get("members") or ():
                    if not isinstance(member, Mapping):
                        continue
                    context_ref = _context_ref_from_member(
                        member=member,
                        source_turn_id=source_turn_id,
                        role="used_context",
                        provenance=provenance,
                    )
                    if context_ref is not None and context_ref.ref == ref:
                        supplied_refs.setdefault(ref, context_ref)
    refs.update(supplied_refs)
    artifact = artifact_ref(
        answer_text=answer_text,
        source_turn_id=source_turn_id,
        route_id=message_id,
    )
    stale = tuple(StaleRef.model_validate(item) for item in stale_refs)
    return MessageContextManifest(
        message_id=str(message_id), run_id=str(run_id), source_turn_id=str(source_turn_id),
        considered_context=considered,
        cited_evidence=cited,
        context_refs=tuple(refs.values()),
        # Reference sets and target refs are legacy resolver data. Keep the
        # fields in the schema for replay, but never create them for new turns.
        reference_sets=(),
        artifacts=(artifact,) if artifact else (), stale_refs=stale,
        provenance=provenance,
    )


def validate_manifest(manifest: Mapping[str, Any], *, supplied_context_refs: set[str] | None = None) -> list[str]:
    """Validate a serialized manifest at API/replay boundaries."""
    try:
        parsed = MessageContextManifest.model_validate(manifest)
    except Exception as exc:  # Pydantic's error shape is intentionally not leaked.
        return [f"manifest_schema:{type(exc).__name__}"]
    issues: list[str] = []
    if parsed.manifest_schema != MESSAGE_CONTEXT_SCHEMA:
        issues.append("unsupported_manifest_schema")
    if supplied_context_refs is not None:
        dangling = [item.ref for item in parsed.context_refs if item.role != "target" and item.ref not in supplied_context_refs]
        issues.extend(f"context_ref_not_supplied:{ref}" for ref in dangling)
    return issues


def source_revision_digest(manifest: MessageContextManifest | Mapping[str, Any]) -> str:
    parsed = (
        manifest
        if isinstance(manifest, MessageContextManifest)
        else MessageContextManifest.model_validate(manifest)
    )
    rows = sorted(
        f"{item.evidence_id}:{item.revision if item.revision is not None else '-'}"
        for item in parsed.considered_context
    )
    return "sha256:" + hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


async def persist_message_context(session, *, user_id, ledger_key: str | None,
                                  manifest: MessageContextManifest):
    """Insert or idempotently replace the single manifest owned by a run."""
    from sqlalchemy import select

    from app.db.models import DialogMessageContext

    run_uuid = uuid.UUID(manifest.run_id)
    row = await session.scalar(
        select(DialogMessageContext).where(
            DialogMessageContext.run_id == run_uuid,
            DialogMessageContext.user_id == user_id,
        )
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    if row is None:
        row = DialogMessageContext(
            id=uuid.uuid4(), message_id=manifest.message_id, run_id=run_uuid,
            user_id=user_id, ledger_key=str(ledger_key or ""),
            manifest_schema=manifest.manifest_schema, manifest=payload,
            source_revision_digest=source_revision_digest(manifest),
        )
        session.add(row)
    else:
        row.message_id = manifest.message_id
        row.ledger_key = str(ledger_key or "")
        row.manifest_schema = manifest.manifest_schema
        row.manifest = payload
        row.source_revision_digest = source_revision_digest(manifest)
    await session.flush()
    return row


async def load_message_context(session, *, user_id, run_id=None, message_id: str | None = None):
    from sqlalchemy import select

    from app.db.models import DialogMessageContext

    stmt = select(DialogMessageContext).where(DialogMessageContext.user_id == user_id)
    if run_id is not None:
        stmt = stmt.where(DialogMessageContext.run_id == run_id)
    elif message_id:
        stmt = stmt.where(DialogMessageContext.message_id == message_id)
    else:
        return None
    return await session.scalar(stmt)


async def load_recent_message_contexts(
    session, *, user_id, ledger_key: str | None, limit: int = 6
) -> tuple[dict[str, Any], ...]:
    if not ledger_key:
        return ()
    from sqlalchemy import select

    from app.db.models import DialogMessageContext

    rows = (
        await session.scalars(
            select(DialogMessageContext)
            .where(
                DialogMessageContext.user_id == user_id,
                DialogMessageContext.ledger_key == ledger_key,
            )
            .order_by(DialogMessageContext.created_at.desc())
            .limit(max(1, min(limit, 20)))
        )
    ).all()
    return tuple(dict(row.manifest or {}) for row in rows)


__all__ = [
    "MESSAGE_CONTEXT_SCHEMA", "REFERENT_RESOLUTION_SCHEMA", "MessageContextManifest",
    "ReferentResolution", "build_message_context_manifest", "validate_manifest",
    "persist_message_context", "load_message_context", "source_revision_digest",
    "evidence_id_aliases", "supplied_object_refs",
    "load_recent_message_contexts",
]
