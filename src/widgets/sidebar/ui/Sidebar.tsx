"use client";

import { Suspense } from "react";

import { SidebarFallback } from "@/widgets/sidebar/ui/sidebar-fallback";
import { SidebarInner } from "@/widgets/sidebar/ui/sidebar-inner";

type SidebarProps = {
  onNavigate?: () => void;
};

export function Sidebar({ onNavigate }: SidebarProps) {
  return (
    <Suspense fallback={<SidebarFallback />}>
      <SidebarInner onNavigate={onNavigate} />
    </Suspense>
  );
}

export { SidebarFallback };
