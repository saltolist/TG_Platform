from app.schemas.common import ResourceWithId


class PostIn(ResourceWithId):
    """Full Post object (client-generated id). Extra fields preserved."""


class GlobalChatIn(ResourceWithId):
    """Full GlobalChat object (client-generated id)."""


class GlobalNoteIn(ResourceWithId):
    """Full GlobalNote object (client-generated id)."""
