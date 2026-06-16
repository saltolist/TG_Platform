import { POST_NEW_SLUG, STATIC_POST_IDS } from "@/shared/lib/staticParams";

/** Legacy `/post/{id}/notes/` — RouteSync redirects to `/post/{id}/` + notes mode. */
export function generateStaticParams() {
  return STATIC_POST_IDS.filter((id) => id !== POST_NEW_SLUG).map((id) => ({ id }));
}

export default function PostLegacyNotesPage() {
  return null;
}
