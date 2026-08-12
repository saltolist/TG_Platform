"""Workspace resource capability registry."""

from app.services.agent.resources.registry import (
    Capability,
    ResourceDescriptor,
    get_resource_descriptor,
    resource_kinds,
)

__all__ = [
    "Capability",
    "ResourceDescriptor",
    "get_resource_descriptor",
    "resource_kinds",
]
