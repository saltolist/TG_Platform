from app.api.v1.ai import _pick_web_model, _resolve_reply_key, _resolve_web_model_for_reply
from app.db.models import User
from app.services.ai.keys import KeySource


def test_pick_web_model_by_id() -> None:
    profile = {
        "webSearchModels": [
            {"id": "web-1", "provider": "Perplexity", "model": "search-api", "apiKey": "pk-test"},
            {"id": "web-2", "provider": "OpenAI", "model": "responses-api-web-search", "apiKey": "sk-test"},
        ],
    }
    picked = _pick_web_model(profile, "web-1")
    assert picked is not None
    assert picked["model"] == "search-api"


def test_resolve_web_key_from_profile_byok() -> None:
    profile = {
        "webSearchModels": [
            {
                "id": "web-1",
                "provider": "Perplexity",
                "model": "search-api",
                "apiKey": "pplx-secret-key",
                "active": True,
            },
        ],
    }
    user = User(email="writer@example.com", is_seed=False)
    web_model = _resolve_web_model_for_reply(
        profile,
        "web-1",
        "Perplexity",
        "search-api",
    )
    resolution = _resolve_reply_key(user, web_model, None)
    assert resolution.api_key == "pplx-secret-key"
    assert resolution.source == KeySource.BYOK


def test_resolve_web_key_ignores_masked_client_override() -> None:
    profile = {
        "webSearchModels": [
            {
                "id": "web-1",
                "provider": "Perplexity",
                "model": "search-api",
                "apiKey": "pplx-secret-key",
                "active": True,
            },
        ],
    }
    user = User(email="writer@example.com", is_seed=False)
    web_model = _resolve_web_model_for_reply(
        profile,
        "web-1",
        "Perplexity",
        "search-api",
    )
    resolution = _resolve_reply_key(user, web_model, "ppl**********key")
    assert resolution.api_key == "pplx-secret-key"
    assert resolution.source == KeySource.BYOK
