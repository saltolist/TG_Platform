"""Default profile payloads for new accounts (mirror frontend empty-account-state)."""

from __future__ import annotations

from typing import Any


def empty_channel_profile() -> dict[str, Any]:
    return {
        "core": {
            "topic": "",
            "audience": "",
            "promise": "",
            "angle": "",
            "author": "",
        },
        "voice": {"tone": "", "format": "", "phrases": ""},
        "rules": {"must": "", "avoid": ""},
        "rubrics": [],
    }


def empty_ai_profile() -> dict[str, Any]:
    return {
        "llmModels": [],
        "webSearchModels": [],
        "visionModels": [],
        "imageGenerationModels": [],
        "orchestratorModels": [],
        "webReasonerModels": [],
        "ragReasonerModels": [],
        "multiResponseEnabled": False,
        "systemPrompt": "",
    }


def empty_telegram_profile() -> dict[str, Any]:
    return {
        "authStatus": "idle",
        "authStep": "credentials",
        "apiId": "",
        "apiHash": "",
        "phone": "",
        "sessionName": "",
        "sessionString": "",
        "channel": "",
        "channelTitle": "",
        "channelStatus": "idle",
        "syncMode": "history-and-live",
        "lastSync": "—",
        "importedPosts": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }


def empty_profile_payload() -> dict[str, dict[str, Any]]:
    return {
        "channel": empty_channel_profile(),
        "ai": empty_ai_profile(),
        "telegram": empty_telegram_profile(),
    }
