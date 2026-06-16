"use client";

import {
  ThemeProvider as NextThemesProvider,
  type ThemeProviderProps,
} from "next-themes";

/**
 * next-themes injects an inline <script> to prevent theme flash.
 * React 19 warns about script tags inside client components.
 * On SSR the script runs as JS; on client hydration we use type="application/json"
 * so React skips it (theme is already applied from SSR).
 */
export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  const scriptProps =
    typeof window === "undefined" ? undefined : ({ type: "application/json" } as const);

  return (
    <NextThemesProvider
      attribute={["class", "data-theme"]}
      defaultTheme="system"
      enableSystem
      storageKey="tg-platform-theme"
      disableTransitionOnChange
      scriptProps={scriptProps}
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}
