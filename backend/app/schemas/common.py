from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Permissive base: preserves all client fields (model is stored as JSONB)."""

    model_config = ConfigDict(extra="allow")


class ResourceWithId(ApiModel):
    id: str


class ErrorResponse(BaseModel):
    error: str
