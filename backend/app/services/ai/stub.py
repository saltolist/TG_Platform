"""AI assistant — Phase 1 stub.

Real LLM integration (BYOK from AiProfileConfig, streaming, web-search, RAG)
arrives in Phase 2. See docs/backend/roadmap.md.
"""


def generate_reply(text: str, scope: str = "global") -> str:
    scope_label = "пост" if scope == "post" else "глобальный"
    return (
        f"[AI-заглушка · {scope_label} контекст] Запрос принят: «{text.strip()}».\n\n"
        "Реальная интеграция с LLM появится в Фазе 2 "
        "(см. docs/backend/roadmap.md)."
    )
