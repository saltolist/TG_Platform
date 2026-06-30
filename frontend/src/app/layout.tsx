import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { AppProviders } from "@/app/providers/AppProviders";
import "./globals.css";
import "./styles/shell-auth.css";
/* Legacy parity: profile styles as a separate entry (see web-legacy layout.tsx) */
import "./styles/shell-profile-page.css";
/* Mobile composer + no-zoom — после profile, чтобы перебить 14px поля */
import "./styles/shell-mobile-composer.css";

export const metadata: Metadata = {
  title: "TG Platform",
  description: "AI operating system for Telegram channel authors",
};

/**
 * Static export (GitHub Pages / MSW demo) has no server proxy/middleware and
 * therefore cannot set response headers or a per-request nonce.  In that build
 * we emit a permissive meta-CSP that still blocks the most dangerous vectors
 * (object-src, base-uri, frame-ancestors) without breaking the demo.
 *
 * For the Next.js server build (Docker), the CSP is set per-request by
 * src/proxy.ts — no meta tag is emitted, and `headers()` is NOT called here so
 * that pages remain statically optimizable.
 *
 * IS_STATIC_EXPORT is a build-time constant (GITHUB_PAGES env), so the meta tag
 * is fully tree-shaken out of the server build.
 */
const IS_STATIC_EXPORT = process.env.GITHUB_PAGES === "true";

const STATIC_META_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "connect-src *",
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
].join("; ");

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ru"
      suppressHydrationWarning
      data-theme="system"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
    >
      <head>
        {IS_STATIC_EXPORT ? (
          <meta httpEquiv="Content-Security-Policy" content={STATIC_META_CSP} />
        ) : null}
      </head>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
