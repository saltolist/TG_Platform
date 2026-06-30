/**
 * Next.js Edge Middleware — security headers + CSP (Report-Only).
 *
 * Runs only when Next.js acts as a server (Docker / standalone output).
 * Static export (GitHub Pages) has no server middleware; a lighter
 * <meta http-equiv="Content-Security-Policy"> is injected in layout.tsx instead.
 *
 * CSP strategy: nonce-based strict CSP.
 *   script-src 'nonce-<random>' 'strict-dynamic'
 * "strict-dynamic" lets scripts loaded by a trusted (nonced) script load
 * further scripts without listing each origin explicitly.
 *
 * We start with Content-Security-Policy-Report-Only so violations are logged
 * to the browser console / report endpoint without breaking anything.
 * Switch to Content-Security-Policy once no violations are observed.
 */

import { NextResponse, type NextRequest } from "next/server";

/** Base64url-safe random nonce (128 bits). */
function generateNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Build the CSP directive string.
 *
 * Directives kept intentionally broad on first pass (Report-Only) so we can
 * observe real violations before tightening.  Key choices:
 *
 * - script-src: nonce + strict-dynamic (no 'unsafe-eval'; Next.js dev HMR
 *   needs 'unsafe-eval' in dev so we add it only in development).
 * - style-src: 'unsafe-inline' — Tailwind injects styles this way; removing
 *   it would require CSS-in-JS nonce support which is out of scope here.
 * - connect-src: 'self' + the configured API base URL (covers REST + SSE stream).
 * - img-src: 'self' data: blob: — data: covers note attachments stored as
 *   data-URIs; blob: covers object-URL previews.
 * - frame-ancestors: 'none' — prevents clickjacking (replaces X-Frame-Options).
 */
function buildCsp(nonce: string, apiUrl: string, isDev: boolean): string {
  const scriptSrc = isDev
    ? `'nonce-${nonce}' 'strict-dynamic' 'unsafe-eval'`
    : `'nonce-${nonce}' 'strict-dynamic'`;

  const connectSrc = ["'self'", apiUrl].filter(Boolean).join(" ");

  const directives: Record<string, string> = {
    "default-src": "'self'",
    "script-src": scriptSrc,
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data: blob:",
    "font-src": "'self'",
    "connect-src": connectSrc,
    "media-src": "'self' blob:",
    "object-src": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "frame-ancestors": "'none'",
    "upgrade-insecure-requests": "",
  };

  return Object.entries(directives)
    .map(([k, v]) => (v ? `${k} ${v}` : k))
    .join("; ");
}

export function middleware(request: NextRequest) {
  const nonce = generateNonce();
  const isDev = process.env.NODE_ENV !== "production";

  // Browser-reachable API URL (baked into the build via NEXT_PUBLIC_API_BASE_URL).
  const apiUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

  const csp = buildCsp(nonce, apiUrl, isDev);

  const requestHeaders = new Headers(request.headers);
  // Pass nonce to the page so _document / layout can stamp <script nonce=…>.
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("x-csp", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });

  // ── Security headers ──────────────────────────────────────────────────────
  // CSP: Report-Only — logs violations but does not block anything.
  // Change to "Content-Security-Policy" when ready to enforce.
  response.headers.set("Content-Security-Policy-Report-Only", csp);

  // Prevent MIME-type sniffing (e.g. serving a JS file as text/plain).
  response.headers.set("X-Content-Type-Options", "nosniff");

  // Don't send the full URL as Referer to third-party origins.
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");

  // Disable powerful browser features the app does not use.
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), payment=()",
  );

  // Strict HSTS — only meaningful over HTTPS, browsers ignore it over HTTP.
  if (!isDev) {
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=31536000; includeSubDomains",
    );
  }

  return response;
}

export const config = {
  /*
   * Run on all routes except:
   * - /_next/static  — pre-built static assets (no SSR, no headers needed here)
   * - /_next/image   — Next.js image optimiser
   * - /favicon.ico and common static files
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|otf|eot)).*)",
  ],
};
