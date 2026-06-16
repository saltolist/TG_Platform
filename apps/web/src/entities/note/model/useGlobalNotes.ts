"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/shared/api/queryKeys";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import type { GlobalNote } from "@/shared/types";

export function useGlobalNotes() {
  const { notes } = useRepositories();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.globalNotes.list(accountId),
    queryFn: () => notes.listGlobal(),
    enabled,
    placeholderData: (previous) => previous,
  });
}

export function useUpsertGlobalNote() {
  const { notes } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: (note: GlobalNote) => notes.upsert(note),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.globalNotes.all(accountId) });
    },
  });
}

export function useDeleteGlobalNote() {
  const { notes } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: (noteId: string) => notes.remove(noteId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.globalNotes.all(accountId) });
    },
  });
}
