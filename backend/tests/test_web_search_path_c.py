from app.services.ai.web_search import WebCite, web_cites_to_meta


def test_web_cites_to_meta_shape() -> None:
    cites = [
        WebCite.from_url("https://example.com/a", "Example A"),
        WebCite.from_url("https://example.org/b", "Example B"),
    ]
    meta = web_cites_to_meta(cites)
    assert meta == [
        {"url": "https://example.com/a", "title": "Example A", "domain": "example.com"},
        {"url": "https://example.org/b", "title": "Example B", "domain": "example.org"},
    ]


def test_parse_perplexity_search_results_structure() -> None:
    """Mirror call_perplexity_search parsing for path C."""
    data = {
        "results": [
            {
                "title": "Source 1",
                "url": "https://one.example/post",
                "snippet": "Snippet one",
            },
            {
                "title": "Source 2",
                "url": "https://two.example/post",
                "snippet": "Snippet two",
            },
        ],
    }
    cites: list[WebCite] = []
    context_lines: list[str] = []
    for i, r in enumerate(data.get("results") or [], 1):
        url = str(r.get("url") or "").strip()
        title = str(r.get("title") or "").strip() or url
        snippet = str(r.get("snippet") or r.get("content") or "").strip()
        if url:
            cites.append(WebCite.from_url(url, title))
        if snippet:
            context_lines.append(f"[{i}] {title}\n{snippet}")

    assert len(cites) == 2
    assert cites[0].domain == "one.example"
    assert "[1] Source 1" in context_lines[0]
    assert web_cites_to_meta(cites)[1]["url"] == "https://two.example/post"
