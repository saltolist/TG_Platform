"""Declarative resource capabilities shared by contracts and research tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    CATALOG = "catalog"
    DISCOVER = "discover"
    FULL_TEXT = "full_text"
    METADATA = "metadata"
    VISION = "vision"
    ANALYTICS = "analytics"
    AGGREGATE = "aggregate"
    MUTATE = "mutate"


@dataclass(frozen=True)
class ResourceDescriptor:
    kind: str
    capabilities: frozenset[Capability]
    evidence_kinds: frozenset[str]
    discovery_node_types: tuple[str, ...] = ()
    read_tool: str | None = None
    catalog_statuses: frozenset[str] = frozenset()
    catalog_order_fields: frozenset[str] = frozenset()

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities


_DESCRIPTORS = (
    ResourceDescriptor(
        kind="notes",
        capabilities=frozenset(
            {Capability.CATALOG, Capability.DISCOVER, Capability.FULL_TEXT, Capability.AGGREGATE}
        ),
        evidence_kinds=frozenset({"note_chunk", "semantic_card", "catalog"}),
        discovery_node_types=("note_summary", "note_chunk"),
        read_tool="OpenNote",
    ),
    ResourceDescriptor(
        kind="posts",
        capabilities=frozenset(
            {
                Capability.CATALOG,
                Capability.DISCOVER,
                Capability.FULL_TEXT,
                Capability.AGGREGATE,
                Capability.MUTATE,
            }
        ),
        evidence_kinds=frozenset({"post_text", "semantic_card", "catalog"}),
        discovery_node_types=("post_summary", "post_text"),
        read_tool="OpenPost",
        catalog_statuses=frozenset({"draft", "scheduled", "published"}),
        catalog_order_fields=frozenset({"position", "created_at"}),
    ),
    ResourceDescriptor(
        kind="comments",
        capabilities=frozenset({Capability.CATALOG, Capability.FULL_TEXT}),
        evidence_kinds=frozenset({"comment"}),
        read_tool="ListPostComments",
    ),
    ResourceDescriptor(
        kind="channel",
        capabilities=frozenset({Capability.METADATA, Capability.FULL_TEXT}),
        evidence_kinds=frozenset({"channel_profile"}),
        read_tool="ReadChannel",
    ),
    ResourceDescriptor(
        kind="analytics",
        capabilities=frozenset({Capability.ANALYTICS}),
        evidence_kinds=frozenset({"analytics"}),
        read_tool="GetPostAnalytics",
    ),
    ResourceDescriptor(
        kind="attachments",
        capabilities=frozenset({Capability.CATALOG, Capability.DISCOVER, Capability.FULL_TEXT}),
        evidence_kinds=frozenset({"attachment_text", "media_meta", "catalog"}),
        discovery_node_types=("attachment_text",),
        read_tool="HydrateAttachment",
    ),
    ResourceDescriptor(
        kind="images",
        capabilities=frozenset({Capability.CATALOG, Capability.DISCOVER, Capability.VISION}),
        evidence_kinds=frozenset({"vision", "media_meta", "catalog"}),
        discovery_node_types=("media_meta",),
        read_tool="HydrateAttachment",
    ),
    ResourceDescriptor(
        kind="dialog",
        capabilities=frozenset({Capability.FULL_TEXT}),
        evidence_kinds=frozenset(),
    ),
)

RESOURCE_REGISTRY = {item.kind: item for item in _DESCRIPTORS}


def get_resource_descriptor(kind: str) -> ResourceDescriptor | None:
    return RESOURCE_REGISTRY.get(str(kind or "").strip().lower())


def resource_kinds(*, classifier_visible: bool = False) -> frozenset[str]:
    kinds = frozenset(RESOURCE_REGISTRY)
    return kinds - {"dialog"} if classifier_visible else kinds


__all__ = [
    "Capability",
    "RESOURCE_REGISTRY",
    "ResourceDescriptor",
    "get_resource_descriptor",
    "resource_kinds",
]
