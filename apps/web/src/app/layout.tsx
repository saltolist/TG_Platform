import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppProviders } from "@/app/providers/AppProviders";
import "./globals.css";
import "./styles/shell-auth.css";
/* Legacy parity: profile styles as a separate entry (see web-legacy layout.tsx) */
import "./styles/shell-profile-page.css";
/* Mobile composer + no-zoom — после profile, чтобы перебить 14px поля */
import "./styles/shell-mobile-composer.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin", "cyrillic"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

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
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
