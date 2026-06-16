import type { ChatMessage, Post, PostMedia } from "@/shared/types";

export function truncate(value: string | undefined | null, max: number): string {
  if (!value) return "";
  return value.length > max ? value.slice(0, max) + "…" : value;
}

export function extractTitle(text: string | undefined | null): string {
  if (!text) return "";
  const firstLine = text.split("\n")[0];
  const dotIdx = firstLine.indexOf(".");
  return (dotIdx !== -1 ? firstLine.slice(0, dotIdx) : firstLine).trim();
}

export function postTitle(post: Post): string {
  const base = extractTitle(post.text) || "(без названия)";
  return base;
}

/** Заголовок поста для чипа в composer (без @ и без даты). */
export function attachmentPostTitle(post: Pick<Post, "text">): string {
  return extractTitle(post.text) || "(без названия)";
}

const RU_MONTHS_FULL = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
] as const;

/** Сокращения месяца в родительном падеже (после числа: «22 мая»). */
const RU_MONTHS_SHORT_GENITIVE = [
  "янв",
  "фев",
  "мар",
  "апр",
  "мая",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
] as const;

/** Парсит ISO-8601 дату из модельного слоя. */
export function parsePostDateTime(raw: string | undefined | null): Date | null {
  if (!raw) return null;
  const d = new Date(raw);
  return Number.isFinite(d.getTime()) ? d : null;
}

export function postFreshness(post: Post): number {
  const raw = post.date || post.created;
  if (!raw) return 0;
  return parsePostDateTime(raw)?.getTime() ?? 0;
}

export function postDayStart(post: Post): number {
  const ts = postFreshness(post);
  if (!ts) return 0;
  const d = new Date(ts);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function formatFeedDayLabel(dayStart: number, now = new Date()): string {
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const oneDay = 86_400_000;
  if (dayStart === todayStart) return "Сегодня";
  if (dayStart === todayStart - oneDay) return "Вчера";
  const d = new Date(dayStart);
  const label = `${d.getDate()} ${RU_MONTHS_FULL[d.getMonth()]}`;
  if (d.getFullYear() === now.getFullYear()) return label;
  return `${label} ${d.getFullYear()}`;
}

/** Дата и время публикации для карточки: «28 апр · 14:22» (месяц в родительном падеже). */
export function formatPostDateTime(date = new Date()): string {
  const day = date.getDate();
  const mon = RU_MONTHS_SHORT_GENITIVE[date.getMonth()];
  const h = String(date.getHours()).padStart(2, "0");
  const m = String(date.getMinutes()).padStart(2, "0");
  return `${day} ${mon} · ${h}:${m}`;
}

function formatPostDateTimeUtc(date: Date): string {
  const day = date.getUTCDate();
  const mon = RU_MONTHS_SHORT_GENITIVE[date.getUTCMonth()];
  const h = String(date.getUTCHours()).padStart(2, "0");
  const m = String(date.getUTCMinutes()).padStart(2, "0");
  return `${day} ${mon} · ${h}:${m}`;
}

function formatPostDateUtc(date: Date): string {
  const day = date.getUTCDate();
  const mon = RU_MONTHS_SHORT_GENITIVE[date.getUTCMonth()];
  return `${day} ${mon}`;
}

function isDateOnlyIso(raw: string): boolean {
  return /T00:00:00(\.000)?Z?$/i.test(raw.trim());
}

/** Форматирует ISO-строку из модельного слоя для UI. */
export function formatStoredDate(raw: string | undefined | null): string {
  const trimmed = raw?.trim();
  if (!trimmed) return "";
  const d = parsePostDateTime(trimmed);
  if (!d) return trimmed;
  if (isDateOnlyIso(trimmed)) return formatPostDateUtc(d);
  return formatPostDateTimeUtc(d);
}

export function postStatusIcon(post: Post): string {
  if (post.status === "published") return "📢";
  if (post.status === "scheduled") return "🕐";
  return "📝";
}

function formatModelDateTime(raw: string | undefined): string {
  return formatStoredDate(raw);
}

export function postStatusLabel(post: Post): string {
  if (post.status === "published") {
    const label = post.date ? formatModelDateTime(post.date) : "";
    return `Опубликован${label ? ` · ${label}` : ""}`;
  }
  if (post.status === "scheduled") {
    const label = post.date ? formatModelDateTime(post.date) : "";
    return `Отложен${label ? ` · ${label}` : ""}`;
  }
  const label = post.created ? formatModelDateTime(post.created) : "";
  return `Черновик${label ? ` · ${label}` : ""}`;
}

export function shortComposerLabel(value: string, maxLen = 22): string {
  const text = String(value || "").trim();
  if (text.length <= maxLen) return text;
  return text.slice(0, Math.max(0, maxLen - 2)) + "..";
}

export function autoResize(el: HTMLTextAreaElement, maxLines: number = 5): void {
  const cs = window.getComputedStyle(el);
  let lineHeight = parseFloat(cs.lineHeight);
  if (!Number.isFinite(lineHeight) || lineHeight <= 0) {
    lineHeight = parseFloat(cs.fontSize) * 1.4;
  }
  const paddingTop = parseFloat(cs.paddingTop) || 0;
  const paddingBottom = parseFloat(cs.paddingBottom) || 0;
  const borderTop = parseFloat(cs.borderTopWidth) || 0;
  const borderBottom = parseFloat(cs.borderBottomWidth) || 0;
  const maxHeight = lineHeight * maxLines + paddingTop + paddingBottom + borderTop + borderBottom;
  el.style.height = "auto";
  const desired = el.scrollHeight;
  if (desired > maxHeight) {
    el.style.height = maxHeight + "px";
    el.style.overflowY = "auto";
  } else {
    el.style.height = desired + "px";
    el.style.overflowY = "hidden";
  }
}

export function getPostMediaItems(post: Post | null | undefined): PostMedia[] {
  if (!post) return [];
  if (Array.isArray(post.media)) return post.media;
  return [];
}

export function isImageMedia(m: PostMedia): boolean {
  return (
    m.type.startsWith("image/") ||
    /\.(png|jpe?g|gif|webp|avif|svg)$/i.test(m.name) ||
    /^data:image\//i.test(m.url)
  );
}

export function isVideoMedia(m: PostMedia): boolean {
  return m.type.startsWith("video/") || /\.(mp4|webm|mov|m4v)$/i.test(m.name);
}

function userMessagePlainText(m: ChatMessage): string {
  if (m.role !== "user") return "";
  if (m.userBranches?.length) {
    const i = Math.min(m.activeUserBranch ?? 0, m.userBranches.length - 1);
    return (m.userBranches[i]?.text || m.userBranches[0]?.text || "").trim();
  }
  return (m.text || "").trim();
}

function aiMessagePlainText(m: ChatMessage): string {
  if (m.role !== "ai") return "";
  if (m.variants?.length) {
    const i = Math.min(m.selectedVariant ?? 0, m.variants.length - 1);
    return (m.variants[i]?.text || m.variants[0]?.text || "").trim();
  }
  return (m.text || "").trim();
}

function chatLineOneLine(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/** Первая реплика пользователя для списка чатов (fallback — заголовок чата). */
export function chatListUserLine(history: ChatMessage[], fallbackTitle: string): string {
  for (const msg of history) {
    const t = userMessagePlainText(msg);
    if (t) return chatLineOneLine(t);
  }
  return chatLineOneLine(fallbackTitle || "Без названия");
}

/** Первый ответ ассистента для списка чатов (fallback — превью). */
export function chatListAssistantLine(history: ChatMessage[], fallbackPreview: string): string {
  for (const msg of history) {
    const t = aiMessagePlainText(msg);
    if (t) return chatLineOneLine(t);
  }
  return chatLineOneLine(fallbackPreview || "");
}

export function readFileAsMedia(file: File): Promise<PostMedia> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve({
        name: file.name,
        url: typeof reader.result === "string" ? reader.result : "",
        type: file.type || "",
      });
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
