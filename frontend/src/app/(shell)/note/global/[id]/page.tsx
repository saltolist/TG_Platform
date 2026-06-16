import { Suspense } from "react";
import { NoteScreen } from "@/screens/note";
import { STATIC_GLOBAL_NOTE_IDS } from "@/shared/lib/staticParams";

export function generateStaticParams() {
  return STATIC_GLOBAL_NOTE_IDS.map((id) => ({ id }));
}

export default function GlobalNotePage() {
  return (
    <Suspense fallback={null}>
      <NoteScreen />
    </Suspense>
  );
}
