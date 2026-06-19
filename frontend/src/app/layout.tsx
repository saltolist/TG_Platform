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
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
