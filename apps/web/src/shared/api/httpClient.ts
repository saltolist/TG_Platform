import { API_BASE_URL, USE_MSW } from "@/shared/config/dataSource";
import { getApiAuthToken } from "@/shared/lib/auth/session";

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export function clearUnauthorizedHandler(): void {
  onUnauthorized = null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (!API_BASE_URL && !USE_MSW) {
    throw new ApiError("NEXT_PUBLIC_API_BASE_URL is not configured", 0);
  }

  if (USE_MSW && typeof window !== "undefined") {
    const { ensureMswStarted } = await import("@/shared/api/msw/browser");
    await ensureMswStarted();
  }

  const { method = "GET", body, signal } = options;
  const headers: HeadersInit = {};
  const token = getApiAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const url = API_BASE_URL ? `${API_BASE_URL}${path}` : path;

  const res = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!res.ok) {
    if (res.status === 401) {
      onUnauthorized?.();
      throw new ApiError("Unauthorized", 401);
    }
    let payload: unknown;
    try {
      payload = await res.json();
    } catch {
      payload = await res.text().catch(() => undefined);
    }
    throw new ApiError(`API ${method} ${path} failed (${res.status})`, res.status, payload);
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}
