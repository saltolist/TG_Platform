const ALLOWED_TAGS = new Set([
  "strong",
  "em",
  "u",
  "s",
  "code",
  "pre",
  "a",
  "blockquote",
  "span",
  "br",
]);

const DROP_CONTENT_TAGS = new Set(["script", "style", "iframe", "object", "embed"]);

const SAFE_LINK_PREFIXES = ["http://", "https://", "tg://", "mailto:"];

function isSafeHref(value: string): boolean {
  const href = value.trim().toLowerCase();
  if (!href) return false;
  return SAFE_LINK_PREFIXES.some((prefix) => href.startsWith(prefix));
}

function sanitizeNode(node: Node): Node | null {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.cloneNode(false);
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const element = node as HTMLElement;
  const tag = element.tagName.toLowerCase();
  if (!ALLOWED_TAGS.has(tag)) {
    if (DROP_CONTENT_TAGS.has(tag)) {
      return null;
    }
    const fragment = document.createDocumentFragment();
    element.childNodes.forEach((child) => {
      const sanitized = sanitizeNode(child);
      if (sanitized) fragment.appendChild(sanitized);
    });
    return fragment;
  }

  if (tag === "a") {
    const href = element.getAttribute("href") ?? "";
    if (!isSafeHref(href)) {
      const fragment = document.createDocumentFragment();
      element.childNodes.forEach((child) => {
        const sanitized = sanitizeNode(child);
        if (sanitized) fragment.appendChild(sanitized);
      });
      return fragment;
    }
  }

  const clean = document.createElement(tag);
  if (tag === "a") {
    const href = element.getAttribute("href") ?? "";
    clean.setAttribute("href", href);
    clean.setAttribute("rel", "noopener noreferrer");
    clean.setAttribute("target", "_blank");
  } else if (tag === "span") {
    const className = element.getAttribute("class") ?? "";
    if (className.split(/\s+/).includes("tg-spoiler")) {
      clean.setAttribute("class", "tg-spoiler");
    }
  }

  element.childNodes.forEach((child) => {
    const sanitized = sanitizeNode(child);
    if (sanitized) clean.appendChild(sanitized);
  });
  return clean;
}

/** Keep only Telegram-style inline formatting tags from backend HTML. */
export function sanitizeTelegramHtml(html: string): string {
  const trimmed = html.trim();
  if (!trimmed) return "";
  if (typeof DOMParser === "undefined") return trimmed;

  const doc = new DOMParser().parseFromString(trimmed, "text/html");
  const body = doc.body;
  const container = document.createElement("div");
  body.childNodes.forEach((child) => {
    const sanitized = sanitizeNode(child);
    if (sanitized) container.appendChild(sanitized);
  });
  return container.innerHTML;
}
