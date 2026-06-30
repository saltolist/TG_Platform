"""Receive Content-Security-Policy violation reports from browsers.

Browsers POST reports to the URL declared in the CSP ``report-uri`` directive.
No authentication — reports are sent automatically by the user agent.

Typical Content-Types:
  - ``application/csp-report`` (legacy)
  - ``application/reports+json`` (Reporting API)
  - ``application/json``
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/csp-report", tags=["Security"])
_logger = logging.getLogger("tg.security.csp")

_MAX_LOG_CHARS = 4000


@router.post("/", status_code=204)
async def receive_csp_report(request: Request) -> Response:
    """Accept a CSP violation report and write it to the application log."""
    body = await request.body()
    if body:
        text = body.decode("utf-8", errors="replace")
        if len(text) > _MAX_LOG_CHARS:
            text = text[:_MAX_LOG_CHARS] + "…"
        _logger.warning(
            "CSP violation (ct=%s): %s",
            request.headers.get("content-type", ""),
            text,
        )
    return Response(status_code=204)
