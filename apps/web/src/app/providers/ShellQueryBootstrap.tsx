"use client";

import { useGlobalChats } from "@/entities/chat";
import { useTelegramProfile } from "@/entities/channel";
import { useGlobalNotes } from "@/entities/note";
import { usePosts } from "@/entities/post";

/**
 * Keeps core list + telegram queries subscribed at shell level (outside Sidebar Suspense)
 * so navigation does not drop observers and refetch from scratch.
 */
export function ShellQueryBootstrap() {
  usePosts();
  useGlobalChats();
  useGlobalNotes();
  useTelegramProfile();
  return null;
}
