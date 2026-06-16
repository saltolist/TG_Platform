import { API_MODE, USE_MSW } from "@/shared/config/dataSource";
import { createHttpRepositories, createMswRepositories } from "@/shared/api/httpRepositories";
import type { RepositoryBundle } from "@/shared/api/repositories";
import { createSeedRepositories } from "@/shared/api/seedRepositories";

export function createRepositories(): RepositoryBundle {
  if (API_MODE) return createHttpRepositories();
  if (USE_MSW) return createMswRepositories();
  return createSeedRepositories();
}

let cached: RepositoryBundle | null = null;

export function getRepositories(): RepositoryBundle {
  if (!cached) cached = createRepositories();
  return cached;
}

export function resetRepositoriesForTests(): void {
  cached = null;
}
