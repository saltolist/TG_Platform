import { API_BASE_URL, API_MODE } from "@/shared/config/dataSource";
import { apiV1Path } from "@/shared/config/basePath";
import { getApiAuthToken } from "@/shared/lib/auth/session";

export type EmojiPreviewResult =
  | { kind: "image"; url: string }
  | { kind: "video"; url: string }
  | { kind: "lottie"; data: object };

export class EmojiPreviewError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly permanent: boolean,
  ) {
    super(message);
    this.name = "EmojiPreviewError";
  }
}

const previewCache = new Map<string, EmojiPreviewResult>();
const inflight = new Map<string, Promise<EmojiPreviewResult>>();
const MAX_CONCURRENT = 8;
let activeFetches = 0;
const waitQueue: Array<() => void> = [];

function runNextQueued(): void {
  if (activeFetches >= MAX_CONCURRENT || waitQueue.length === 0) return;
  const next = waitQueue.shift();
  next?.();
}

function withConcurrencyLimit<T>(task: () => Promise<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const run = () => {
      activeFetches += 1;
      task()
        .then(resolve, reject)
        .finally(() => {
          activeFetches -= 1;
          runNextQueued();
        });
    };

    if (activeFetches < MAX_CONCURRENT) {
      run();
    } else {
      waitQueue.push(run);
    }
  });
}

/** Browser-reachable preview API URL (includes API host when configured). */
export function emojiPreviewApiUrl(documentId: string): string {
  const path = apiV1Path(`telegram/emoji/${encodeURIComponent(documentId)}/preview/`);
  if (!API_BASE_URL) return path;
  return `${API_BASE_URL}${path}`;
}

export function telegramEmojiPreviewUrl(documentId: string): string {
  return emojiPreviewApiUrl(documentId);
}

function classifyPreviewBytes(buffer: ArrayBuffer, contentType: string): EmojiPreviewResult {
  const bytes = new Uint8Array(buffer);
  const normalizedType = contentType.toLowerCase();

  if (
    normalizedType.includes("application/json") ||
    (bytes.length > 0 && bytes[0] === 0x7b)
  ) {
    const data = JSON.parse(new TextDecoder().decode(bytes)) as object;
    return { kind: "lottie", data };
  }

  if (bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
    throw new Error("emoji preview returned raw TGS");
  }

  if (
    normalizedType.startsWith("video/") ||
    (bytes.length > 3 && bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf)
  ) {
    const videoType = normalizedType.startsWith("video/") ? normalizedType : "video/webm";
    const blob = new Blob([buffer], { type: videoType });
    return { kind: "video", url: URL.createObjectURL(blob) };
  }

  const imageType = normalizedType.startsWith("image/") ? normalizedType : "image/webp";
  const blob = new Blob([buffer], { type: imageType });
  return { kind: "image", url: URL.createObjectURL(blob) };
}

async function fetchEmojiPreviewUncached(documentId: string): Promise<EmojiPreviewResult> {
  const url = emojiPreviewApiUrl(documentId);
  const headers: HeadersInit = {};
  const token = getApiAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    credentials: API_MODE ? "include" : "same-origin",
    headers,
  });
  if (!response.ok) {
    const permanent = response.status === 400 || response.status === 404;
    throw new EmojiPreviewError(`emoji preview ${response.status}`, response.status, permanent);
  }

  const buffer = await response.arrayBuffer();
  const contentType = response.headers.get("content-type") ?? "";
  return classifyPreviewBytes(buffer, contentType);
}

export function fetchEmojiPreview(documentId: string): Promise<EmojiPreviewResult> {
  const cached = previewCache.get(documentId);
  if (cached) return Promise.resolve(cached);

  const pending = inflight.get(documentId);
  if (pending) return pending;

  const promise = withConcurrencyLimit(() => fetchEmojiPreviewUncached(documentId))
    .then((result) => {
      previewCache.set(documentId, result);
      return result;
    })
    .finally(() => {
      inflight.delete(documentId);
    });

  inflight.set(documentId, promise);
  return promise;
}

export function clearEmojiPreviewCache(): void {
  for (const result of previewCache.values()) {
    if (result.kind === "image" || result.kind === "video") {
      URL.revokeObjectURL(result.url);
    }
  }
  previewCache.clear();
  inflight.clear();
}
