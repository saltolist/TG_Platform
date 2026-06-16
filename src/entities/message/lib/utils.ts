import type { ChatMessage } from "@/shared/types";

export const USER_EDIT_MIN_W = 200;
export const USER_EDIT_MAX_W = 400;

export function assistantPlainText(message: ChatMessage): string {
  if (message.role !== "ai") return "";
  if (Array.isArray(message.variants) && message.variants.length > 0) {
    const selectedIdx = Math.min(
      Math.max(Number(message.selectedVariant) || 0, 0),
      message.variants.length - 1,
    );
    return message.variants[selectedIdx]?.text ?? "";
  }
  return message.text ?? "";
}

export function modelTooltipText(message: ChatMessage): string {
  if (message.role !== "ai") return "";
  if (Array.isArray(message.variants) && message.variants.length > 0) {
    const selectedIdx = Math.min(
      Math.max(Number(message.selectedVariant) || 0, 0),
      message.variants.length - 1,
    );
    const sel = message.variants[selectedIdx];
    const llm = sel?.llmCaption?.trim() ?? "";
    const web = sel?.webCaption?.trim() ?? "";
    if (llm && web) return `${llm} + ${web}`;
    if (llm) return llm;
    if (web) return web;
    return (sel?.label ?? "").trim();
  }
  const llm = message.llmLabel?.trim() ?? "";
  const web = message.webLabel?.trim() ?? "";
  if (llm && web) return `${llm} + ${web}`;
  if (llm) return llm;
  if (web) return web;
  return (message.targetLabel ?? "").trim();
}

export async function copyPlainText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function measureUserEditTextWidth(
  text: string,
  ta: HTMLTextAreaElement,
  maxWidth: number,
): number {
  const cs = window.getComputedStyle(ta);
  const mirror = document.createElement("div");
  mirror.setAttribute("aria-hidden", "true");
  Object.assign(mirror.style, {
    position: "absolute",
    visibility: "hidden",
    pointerEvents: "none",
    top: "0",
    left: "-9999px",
    boxSizing: "border-box",
    maxWidth: `${maxWidth}px`,
    width: "max-content",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    overflowWrap: "anywhere",
    fontFamily: cs.fontFamily,
    fontSize: cs.fontSize,
    fontWeight: cs.fontWeight,
    lineHeight: cs.lineHeight,
    letterSpacing: cs.letterSpacing,
    padding: cs.padding,
  });
  mirror.textContent = text.length > 0 ? text : " ";
  document.body.appendChild(mirror);
  const w = Math.ceil(mirror.getBoundingClientRect().width);
  mirror.remove();
  return Math.min(maxWidth, Math.max(USER_EDIT_MIN_W, w + 2));
}

export function messageTextHtml(message: ChatMessage, userShown: string): string {
  const isUser = message.role === "user";
  if (isUser) return userShown.replace(/\n/g, "<br>");
  if (Array.isArray(message.variants) && message.variants.length > 0) {
    const selectedIdx = Math.min(
      Math.max(Number(message.selectedVariant) || 0, 0),
      message.variants.length - 1,
    );
    return (message.variants[selectedIdx]?.text || "").replace(/\n/g, "<br>");
  }
  return (message.text ?? "").replace(/\n/g, "<br>");
}
