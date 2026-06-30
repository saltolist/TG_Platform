"""Normalize and inject note citation markdown in assistant replies."""

from __future__ import annotations

import re
from dataclasses import dataclass

NOTE_CITE_LINK_RE = re.compile(
    r"\s*\[([^\]]+)\]\((/note/[^)]+|note:(?:global|post)/[^)]+)\)"
)
CITE_PATH_TITLE_RE = re.compile(
    r"cite-path:\s*(/note/\S+?)\s+cite-title:\s*([^\n\[\]]+?)(?=\s*(?:\n|---|$))",
    re.IGNORECASE,
)
CITE_PATH_IN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(\s*cite-path:\s*(/note/[^)\s]+)\s*\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NoteCite:
    path: str
    title: str


def _normalize_cite_path(path: str) -> str:
    """Canonical form for comparing note citation targets."""
    raw = path.strip()
    if raw.startswith("note:global/"):
        note_id = raw[len("note:global/") :].strip("/")
        return f"/note/global/{note_id}/" if note_id else raw
    if raw.startswith("note:post/"):
        rest = raw[len("note:post/") :].strip("/")
        parts = rest.split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return f"/note/post/{parts[0]}/{parts[1]}/"
        return raw
    if raw.startswith("/note/"):
        return raw if raw.endswith("/") else f"{raw}/"
    return raw


def _valid_cite_paths(cites: list[NoteCite]) -> set[str]:
    return {_normalize_cite_path(cite.path) for cite in cites}


def _is_valid_cite_href(href: str, valid_paths: set[str]) -> bool:
    if not valid_paths:
        return False
    return _normalize_cite_path(href) in valid_paths


def strip_invalid_note_citations(text: str, cites: list[NoteCite]) -> str:
    """Remove note citation links/metadata that are not in the RAG cite list."""
    valid_paths = _valid_cite_paths(cites)

    def repl_link(match: re.Match[str]) -> str:
        if _is_valid_cite_href(match.group(2), valid_paths):
            return match.group(0)
        return ""

    out = NOTE_CITE_LINK_RE.sub(repl_link, text)
    out = CITE_PATH_IN_LINK_RE.sub(repl_link, out)
    out = CITE_PATH_TITLE_RE.sub(
        lambda match: match.group(0)
        if _is_valid_cite_href(match.group(1), valid_paths)
        else "",
        out,
    )
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out


def normalize_note_citation_markdown(text: str) -> str:
    out = CITE_PATH_IN_LINK_RE.sub(r"[\1](\2)", text)
    out = CITE_PATH_TITLE_RE.sub(
        lambda match: f"[{match.group(2).strip()}]({match.group(1)})",
        out,
    )
    return out


def _detach_citations_in_paragraph(paragraph: str) -> str:
    cites: list[str] = []

    def repl(match: re.Match[str]) -> str:
        cites.append(f"[{match.group(1)}]({match.group(2)})")
        return " "

    body = NOTE_CITE_LINK_RE.sub(repl, paragraph)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n+", " ", body).strip()
    if not cites:
        return paragraph.strip()

    return f"{body} {' '.join(cites)}".strip()


def detach_note_citations(text: str) -> str:
    if not NOTE_CITE_LINK_RE.search(text):
        return text

    chunks = re.split(r"(\n{2,})", text)
    out: list[str] = []
    for chunk in chunks:
        if re.fullmatch(r"\n+", chunk or ""):
            out.append(chunk)
            continue
        out.append(_detach_citations_in_paragraph(chunk))
    return "".join(out)


def _paragraph_has_cite(paragraph: str, cite: NoteCite) -> bool:
    paths = {cite.path, cite.path.rstrip("/")}
    return any(path in paragraph for path in paths)


def inject_missing_note_citations(text: str, cites: list[NoteCite]) -> str:
    if not cites:
        return text

    has_any_cite_link = bool(NOTE_CITE_LINK_RE.search(text))
    chunks = re.split(r"(\n{2,})", text)
    out: list[str] = []

    for chunk in chunks:
        if re.fullmatch(r"\n+", chunk or ""):
            out.append(chunk)
            continue

        paragraph = chunk.strip()
        if not paragraph:
            continue

        additions: list[str] = []
        for cite in cites:
            if _paragraph_has_cite(paragraph, cite):
                continue
            title = cite.title.strip()
            if title and title.lower() in paragraph.lower():
                additions.append(f"[{title}]({cite.path})")

        if not additions and not has_any_cite_link and len(cites) == 1:
            cite = cites[0]
            title = cite.title.strip() or "Заметка"
            additions.append(f"[{title}]({cite.path})")

        if additions:
            stripped = paragraph.rstrip()
            end_punct = ""
            if stripped and stripped[-1] in ".!?…":
                end_punct = stripped[-1]
                stripped = stripped[:-1].rstrip()
            paragraph = f"{stripped}{end_punct} {' '.join(additions)}".strip()

        out.append(paragraph)

    return "".join(out)


def prepare_note_citations_for_reply(text: str, cites: list[NoteCite] | None = None) -> str:
    cites = cites or []
    normalized = normalize_note_citation_markdown(text)
    validated = strip_invalid_note_citations(normalized, cites)
    with_inject = inject_missing_note_citations(validated, cites)
    return detach_note_citations(with_inject)
