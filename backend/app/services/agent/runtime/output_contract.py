"""Versioned answer output and deterministic groundedness gates.

The answer model is allowed to write prose, but it cannot expand the evidence
boundary or invent a citation.  Keeping this contract in code also makes a
format-only repair distinguishable from a semantic/retrieval retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError


OUTPUT_SCHEMA_V1 = "workspace.answer/v1"


def resolve_output_schema(contract: Mapping[str, Any] | None) -> str:
    raw = str((contract or {}).get("output_schema") or "").strip()
    if not raw:
        raw = f"{((contract or {}).get('output') or {}).get('kind', 'answer')}.v1"
    name, _, version = raw.partition(".")
    safe_name = name.replace("_", "-") or "answer"
    safe_version = version or "v1"
    return f"workspace.{safe_name}/{safe_version}"


class AnswerClaimV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    claim_scope: str | None = None


class AnswerOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    claims: list[AnswerClaimV1] = Field(default_factory=list)
    used_context_refs: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class OutputValidation:
    ok: bool
    schema: str
    issues: tuple[str, ...] = ()
    claims: tuple[dict[str, Any], ...] = ()
    used_context_refs: tuple[str, ...] = ()


def validate_answer_output(
    raw: Any,
    *,
    evidence_ids: set[str],
    factual: bool,
    schema: str = OUTPUT_SCHEMA_V1,
    supplied_context_refs: set[str] | None = None,
    evidence_id_aliases: Mapping[str, str] | None = None,
    evidence_fidelity: Mapping[str, str] | None = None,
    evidence_roles: Mapping[str, str] | None = None,
    allow_optional_only_claims: bool = True,
) -> OutputValidation:
    """Validate schema and require every factual claim to cite verified evidence."""

    try:
        parsed = AnswerOutputV1.model_validate(raw)
    except ValidationError as exc:
        return OutputValidation(
            ok=False,
            schema=schema,
            issues=tuple(error.get("loc", ("answer",))[0].__str__() for error in exc.errors()),
        )

    issues: list[str] = []
    fatal_issues: list[str] = []
    claims_list: list[dict[str, Any]] = []
    for claim in parsed.claims:
        normalized = claim.model_dump(mode="json", exclude_none=True)
        normalized["evidence_ids"] = list(
            dict.fromkeys(
                str((evidence_id_aliases or {}).get(str(item), str(item)))
                for item in normalized.get("evidence_ids") or ()
            )
        )
        claims_list.append(normalized)
    claims = tuple(claims_list)
    for index, claim in enumerate(claims):
        cited = [str(item) for item in claim.get("evidence_ids") or []]
        dangling = [item for item in cited if item not in evidence_ids]
        if dangling:
            issue = f"claims[{index}].dangling_evidence:{','.join(dangling)}"
            issues.append(issue)
            fatal_issues.append(issue)
        scope = str(claim.get("claim_scope") or "")
        if scope in {"exact", "content", "quote", "analytics"} and cited:
            fidelities = {
                str((evidence_fidelity or {}).get(eid) or "full_text") for eid in cited
            }
            if fidelities == {"semantic_card"}:
                issue = f"claims[{index}].exact_claim_requires_full_text"
                issues.append(issue)
                fatal_issues.append(issue)
        if (
            not allow_optional_only_claims
            and cited
            and {
                str((evidence_roles or {}).get(eid) or "supporting")
                for eid in cited
            } == {"supporting_optional"}
        ):
            issue = f"claims[{index}].optional_only_outside_required_corpus"
            issues.append(issue)
            fatal_issues.append(issue)
    if factual and any(not claim.get("evidence_ids") for claim in claims):
        issues.append("factual_claim_requires_evidence")
        fatal_issues.append("factual_claim_requires_evidence")
    used_refs = tuple(dict.fromkeys(str(item) for item in parsed.used_context_refs if str(item)))
    if supplied_context_refs is not None:
        dangling_refs = [item for item in used_refs if item not in supplied_context_refs]
        issues.extend(f"used_context_ref_not_supplied:{item}" for item in dangling_refs)
        used_refs = tuple(item for item in used_refs if item in supplied_context_refs)
    return OutputValidation(
        # Unsupported used refs are stripped and reported, but do not discard a
        # grounded answer. Claim/evidence violations remain fatal.
        ok=not fatal_issues,
        schema=schema,
        issues=tuple(issues),
        claims=claims,
        used_context_refs=used_refs,
    )


def is_factual_profile(contract: Mapping[str, Any], *, researched: bool) -> bool:
    """Return whether an answer is impossible without grounded workspace facts."""

    if not researched:
        return False
    if contract.get("requires_workspace") is False:
        return False
    if int(contract.get("version") or 0) < 2 and contract.get("requires_workspace") is not True:
        return False
    if int(contract.get("version") or 0) >= 2:
        return not bool(contract.get("answerability_without_evidence", False))
    return str(contract.get("task_profile") or "") not in {
        "artifact_revision",
        "channel_profile_draft",
        "mutation_proposal",
        "recommendation",
    }
