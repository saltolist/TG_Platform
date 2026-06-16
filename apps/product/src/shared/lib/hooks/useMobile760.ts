"use client";

import { createMediaQueryHook } from "@/shared/lib/hooks/createMediaQueryHook";

const MQ = "(max-width: 760px)";

export function useMobile760(): boolean {
  return useMobile760Hook();
}

const useMobile760Hook = createMediaQueryHook(MQ);
