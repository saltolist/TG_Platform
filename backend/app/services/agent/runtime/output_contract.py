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


class AnswerOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    claims: list[AnswerClaimV1] = Field(default_factory=list)


@dataclass(frozen=True)
class OutputValidation:
    ok: bool
    schema: str
    issues: tuple[str, ...] = ()
    claims: tuple[dict[str, Any], ...] = ()


def validate_answer_output(
    raw: Any,
    *,
    evidence_ids: set[str],
    factual: bool,
    schema: str = OUTPUT_SCHEMA_V1,
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
    claims = tuple(claim.model_dump(mode="json") for claim in parsed.claims)
    for index, claim in enumerate(claims):
        cited = [str(item) for item in claim.get("evidence_ids") or []]
        dangling = [item for item in cited if item not in evidence_ids]
        if dangling:
            issues.append(f"claims[{index}].dangling_evidence:{','.join(dangling)}")
    if factual and any(not claim.get("evidence_ids") for claim in claims):
        issues.append("factual_claim_requires_evidence")
    return OutputValidation(
        ok=not issues,
        schema=schema,
        issues=tuple(issues),
        claims=claims,
    )


def is_factual_profile(contract: Mapping[str, Any], *, researched: bool) -> bool:
    """Research answers are factual; conversational rewrites are not."""

    if not researched:
        return False
    if contract.get("requires_workspace") is False:
        return False
    if int(contract.get("version") or 0) < 2 and contract.get("requires_workspace") is not True:
        return False
    return str(contract.get("task_profile") or "") not in {
        "artifact_revision",
        "mutation_proposal",
    }
