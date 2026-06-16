"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { getRepositories } from "@/shared/api/createRepositories";
import type { RepositoryBundle } from "@/shared/api/repositories";

const RepositoryContext = createContext<RepositoryBundle | null>(null);

export function RepositoryProvider({ children }: { children: ReactNode }) {
  const repositories = useMemo(() => getRepositories(), []);

  return (
    <RepositoryContext.Provider value={repositories}>{children}</RepositoryContext.Provider>
  );
}

export function useRepositories(): RepositoryBundle {
  const context = useContext(RepositoryContext);
  if (!context) {
    throw new Error("useRepositories must be used inside <RepositoryProvider>");
  }
  return context;
}
