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
    normalized = normalize_note_citation_markdown(text)
    with_inject = inject_missing_note_citations(normalized, cites or [])
    return detach_note_citations(with_inject)
