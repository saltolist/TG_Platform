from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.agent.resources.registry import (
    Capability,
    RESOURCE_REGISTRY,
    resource_kinds,
)
from app.services.agent.runtime.turn_contract import (
    Freshness,
    SourceBudget,
    SourceRequirement,
    SourceScope,
)


def test_registry_exposes_discovery_and_evidence_capabilities() -> None:
    assert RESOURCE_REGISTRY["notes"].supports(Capability.DISCOVER)
    assert RESOURCE_REGISTRY["notes"].discovery_node_types
    assert "note_chunk" in RESOURCE_REGISTRY["notes"].evidence_kinds
    assert RESOURCE_REGISTRY["comments"].read_tool == "ListPostComments"
    assert RESOURCE_REGISTRY["channel"].read_tool == "ReadChannel"
    assert "channel" in resource_kinds(classifier_visible=True)


def test_contract_rejects_unknown_resource_kind() -> None:
    with pytest.raises(ValidationError, match="unsupported resource kind"):
        SourceRequirement(
            source_id="unknown",
            kind="case_specific_magic",
            role="source",
            required=True,
            query_goal="read unsupported source",
            scope=SourceScope(mode="corpus", corpus="workspace"),
            freshness=Freshness(mode="latest_available"),
            budget=SourceBudget(
                search_calls=0,
                rewrite_calls=0,
                candidate_limit=1,
                deep_reads=1,
            ),
        )
