import { initialGlobalChats } from "@/shared/data/seed-data";
import { PRESENTATION_GLOBAL_CHAT_IDS } from "@/shared/data/presentation-seed";

/** Legacy `/gchat/{id}/` — RouteSync redirects to `/gchat/?id={id}`. */
export function generateStaticParams() {
  const ids = [...new Set([...initialGlobalChats.map((c) => c.id), ...PRESENTATION_GLOBAL_CHAT_IDS])];
  return ids.map((id) => ({ id }));
}

export default function GChatLegacyPage() {
  return null;
}
