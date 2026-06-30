import { z } from "zod";

import type { WebCite } from "@/shared/api/schemas/post";

const webCiteSchema = z.object({
  url: z.string(),
  title: z.string(),
  domain: z.string(),
});

export const WEB_CITE_MARKER_RE = /\[(\d+)\]/g;

/** [1][2] glued before sentence punctuation → ". [1][2]" */
const WEB_CITE_BEFORE_PUNCT_RE = /(\s*)((?:\[\d+\])+)\s*([.!?])/g;

export const WEB_CITE_HREF_PREFIX = "webcite:";

/** True if text contains Perplexity-style numeric citation markers. */
export function hasWebCitationMarkers(text: string): boolean {
  WEB_CITE_MARKER_RE.lastIndex = 0;
  return WEB_CITE_MARKER_RE.test(text);
}

/** Move numeric markers from before ".!?" to after punctuation with a space. */
export function detachWebCitationMarkers(text: string): string {
  if (!hasWebCitationMarkers(text)) return text;
  return text.replace(WEB_CITE_BEFORE_PUNCT_RE, "$3 $2");
}

/**
 * Replace [1], [2] with markdown links that render as inline web chips.
 * Markers stay visible until webCites are available (e.g. during streaming).
 */
export function injectWebCitationPlaceholders(text: string, webCites: WebCite[]): string {
  if (!webCites.length) return text;
  return text.replace(WEB_CITE_MARKER_RE, (match, numStr: string) => {
    const index = Number.parseInt(numStr, 10);
    if (!webCites[index - 1]) return match;
    return `[](${WEB_CITE_HREF_PREFIX}${index})`;
  });
}

export function prepareWebCitationsForDisplay(text: string, webCites?: WebCite[]): string {
  const detached = detachWebCitationMarkers(text);
  if (!webCites?.length) return detached;
  return injectWebCitationPlaceholders(detached, webCites);
}

/** Parse web_cites from SSE meta without failing the whole meta block. */
export function parseWebCitesFromStreamMeta(
  meta: Record<string, unknown>,
): WebCite[] {
  const raw = meta.web_cites;
  if (!Array.isArray(raw) || raw.length === 0) return [];
  const parsed = z.array(webCiteSchema).safeParse(raw);
  return parsed.success ? parsed.data : [];
}

export function resolveWebCitationHref(href: string): number | null {
  if (!href.startsWith(WEB_CITE_HREF_PREFIX)) return null;
  const index = Number.parseInt(href.slice(WEB_CITE_HREF_PREFIX.length), 10);
  return Number.isFinite(index) && index > 0 ? index : null;
}
