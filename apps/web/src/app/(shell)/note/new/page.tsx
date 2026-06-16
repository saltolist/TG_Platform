"use client";

import { Suspense } from "react";
import { NoteScreen } from "@/screens/note";

export default function NewNotePage() {
  return (
    <Suspense fallback={null}>
      <NoteScreen />
    </Suspense>
  );
}
