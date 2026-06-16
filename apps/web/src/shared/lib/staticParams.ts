import { initialGlobalNotes, initialPosts } from "@/shared/data/seed-data";
import {
  PRESENTATION_GLOBAL_CHAT_IDS,
  PRESENTATION_GLOBAL_NOTE_IDS,
  PRESENTATION_POST_IDS,
} from "@/shared/data/presentation-seed";
import { POST_NEW_SLUG } from "@/shared/lib/routes";

export { POST_NEW_SLUG };

export const STATIC_POST_IDS = [
  ...new Set([...initialPosts.map((p) => p.id), ...PRESENTATION_POST_IDS.map(String)]),
];
export const STATIC_GLOBAL_NOTE_IDS = [
  ...new Set([...initialGlobalNotes.map((n) => n.id), ...PRESENTATION_GLOBAL_NOTE_IDS]),
];

export function staticPostNoteParams(): { postId: string; noteId: string }[] {
  const out: { postId: string; noteId: string }[] = [];
  for (const p of initialPosts) {
    for (const n of p.notes) {
      out.push({ postId: String(p.id), noteId: String(n.id) });
    }
  }
  return out;
}

export const STATIC_GLOBAL_CHAT_IDS = [
  ...new Set(["gc1", "gc2", ...PRESENTATION_GLOBAL_CHAT_IDS]),
];
