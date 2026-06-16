import { Suspense } from "react";
import { NoteScreen } from "@/screens/note";
import { staticPostNoteParams } from "@/shared/lib/staticParams";

export function generateStaticParams() {
  return staticPostNoteParams();
}

export default function PostNotePage() {
  return (
    <Suspense fallback={null}>
      <NoteScreen />
    </Suspense>
  );
}
