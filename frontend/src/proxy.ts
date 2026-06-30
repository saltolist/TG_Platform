/**
 * Next.js Proxy (formerly "middleware") — security headers + CSP (Report-Only).
 *
 * Runs only when Next.js acts as a server (Docker / standalone output).
 * Static export (GitHub Pages) has no proxy; a lighter
 * <meta http-equiv="Content-Security-Policy"> is injected in layout.tsx instead.
 *
 * CSP strategy for Next.js SSG/standalone:
 *   script-src 'self' 'unsafe-inline'
 * Per-request nonce + strict-dynamic only works when pages are rendered
 * dynamically on every request. Our Docker build pre-renders pages statically,
 * so inline hydration scripts are baked without a nonce — nonce-only CSP would
 * break the app if switched to enforce mode.
 *
 * The browser-facing response uses Content-Security-Policy-Report-Only so
 * violations are logged without blocking anything. Switch to
 * Content-Security-Policy (enforce) once the console is clean — see
 * docs/dev/security-byok.md#csp.
 */

import { NextResponse, type NextRequest } from "next/server";

/**
 * Build the CSP directive string.
 *
 * Key choices:
 * - script-src: 'self' + 'unsafe-inline' — required for Next.js static/SSG
 *   hydration bootstrap scripts. External chunks load from 'self' (_next/static).
 * - style-src: 'unsafe-inline' — Tailwind / CSS-in-JS.
 * - connect-src: 'self' + API URL (REST + SSE streaming).
 * - img-src: data: blob: — note attachments and object-URL previews.
 */
function buildCsp(apiUrl: string, isDev: boolean): string {
  const scriptSrc = isDev
    ? "'self' 'unsafe-inline' 'unsafe-eval'"
    : "'self' 'unsafe-inline'";

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
  };

  // upgrade-insecure-requests only makes sense over HTTPS in enforce mode.
  if (!isDev) {
    directives["upgrade-insecure-requests"] = "";
  }

  return Object.entries(directives)
    .map(([k, v]) => (v ? `${k} ${v}` : k))
    .join("; ");
}

export function proxy(request: NextRequest) {
  const isDev = process.env.NODE_ENV !== "production";

  // Browser-reachable API URL (baked into the build via NEXT_PUBLIC_API_BASE_URL).
  const apiUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

  const csp = buildCsp(apiUrl, isDev);

  const response = NextResponse.next({ request });

  // ── Security headers (browser-facing response) ─────────────────────────────
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
   * - /_next/static  — pre-built static assets
   * - /_next/image   — Next.js image optimiser
   * - common static files (favicon, fonts, images)
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|otf|eot)).*)",
  ],
};
