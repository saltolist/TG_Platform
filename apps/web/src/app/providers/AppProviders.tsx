"use client";

import { type ReactNode } from "react";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { ComposerProvider } from "@/app/model/store/composer-store";
import { DialogProvider } from "@/shared/ui/dialog";
import { ErrorBoundary } from "@/shared/ui/error-boundary";
import { ToastProvider } from "@/shared/ui/toast";
import { MswProvider } from "./MswProvider";
import { QueryProvider } from "./QueryProvider";
import { RepositoryProvider } from "./RepositoryProvider";
import { ThemeProvider } from "./ThemeProvider";
import { AuthProvider } from "./AuthProvider";

type AppProvidersProps = {
  children: ReactNode;
};

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <ErrorBoundary>
      <MswProvider>
        <ThemeProvider>
          <ToastProvider>
            <DialogProvider>
              <QueryProvider>
                <AuthProvider>
                  <RepositoryProvider>
                    <ComposerProvider>
                      <TooltipProvider delay={0}>{children}</TooltipProvider>
                    </ComposerProvider>
                  </RepositoryProvider>
                </AuthProvider>
              </QueryProvider>
            </DialogProvider>
          </ToastProvider>
        </ThemeProvider>
      </MswProvider>
    </ErrorBoundary>
  );
}
