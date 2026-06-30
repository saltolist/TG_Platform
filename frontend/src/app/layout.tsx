import type { Metadata } from "next";
import { headers } from "next/headers";
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
 * Static export (GitHub Pages / MSW demo) has no server middleware and therefore
 * no nonce.  In that build we emit a permissive meta-CSP that still blocks the
 * most dangerous vectors (object-src, base-uri) without breaking the demo.
 *
 * When running as a Next.js server (Docker), the middleware stamps x-nonce and
 * x-csp headers on every request; we pick them up here so the <head> can carry
 * the nonce and the CSP is consistent with what the middleware set.
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

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // headers() is only available in server components; returns empty in static export.
  // The nonce set by middleware is consumed by Next.js internally to stamp its own
  // <script> tags; it can also be read here for any custom inline scripts if needed.
  await headers();

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
        {/* nonce is available for future inline scripts via the x-nonce request header */}
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
