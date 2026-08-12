"""Measured runtime limits for Workspace Agent execution profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ProfileLimits:
    db_p95_ms: float
    max_db_calls: int
    max_llm_calls: int
    time_to_final_p95_ms: int | None


# DB limits cover agent-owned queries, not SSE polling or unrelated API work.
# The batch limit is per durable job; its p95 target applies to one page query.
PROFILE_LIMITS: Mapping[str, ProfileLimits] = {
    "exact_lookup": ProfileLimits(100.0, 6, 1, 15_000),
    "topical_answer": ProfileLimits(150.0, 18, 4, 25_000),
    "workspace_synthesis": ProfileLimits(200.0, 24, 4, 25_000),
    "recommendation": ProfileLimits(200.0, 24, 4, 25_000),
    "comparison": ProfileLimits(200.0, 24, 4, 25_000),
    "artifact_revision": ProfileLimits(150.0, 16, 4, 25_000),
    "channel_profile_draft": ProfileLimits(150.0, 16, 4, 25_000),
    "mutation_proposal": ProfileLimits(150.0, 16, 4, 25_000),
    "exhaustive_inventory": ProfileLimits(250.0, 256, 0, None),
}


def limits_for_profile(profile: str) -> ProfileLimits:
    return PROFILE_LIMITS.get(profile, PROFILE_LIMITS["topical_answer"])


def evaluate_profile_limits(
    profile: str,
    *,
    db_p95_ms: float,
    db_calls: int,
    llm_calls: int,
    time_to_final_p95_ms: float | None = None,
) -> list[str]:
    limits = limits_for_profile(profile)
    issues: list[str] = []
    if db_p95_ms > limits.db_p95_ms:
        issues.append("db_p95_ms")
    if db_calls > limits.max_db_calls:
        issues.append("db_calls")
    if llm_calls > limits.max_llm_calls:
        issues.append("llm_calls")
    if (
        limits.time_to_final_p95_ms is not None
        and time_to_final_p95_ms is not None
        and time_to_final_p95_ms > limits.time_to_final_p95_ms
    ):
        issues.append("time_to_final_p95_ms")
    return issues
