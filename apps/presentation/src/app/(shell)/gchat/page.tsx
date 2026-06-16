"use client";

import { Suspense } from "react";
import { GChatScreen } from "@/screens/gchat";

export default function GChatPage() {
  return (
    <Suspense fallback={null}>
      <GChatScreen />
    </Suspense>
  );
}
