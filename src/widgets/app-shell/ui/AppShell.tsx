"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { useNavigationStore, useUiStore } from "@/app/model/store";
import { screenFromPath } from "@/shared/lib/routes";
import { Sidebar } from "@/widgets/sidebar";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const mobileSidebarOpen = useUiStore((s) => s.mobileSidebarOpen);
  const setMobileSidebarOpen = useUiStore((s) => s.setMobileSidebarOpen);
  const screen = screenFromPath(pathname ?? "/");
  const noteDirty = useUiStore((s) => s.noteDirty);
  const isEditingPost = useNavigationStore((s) => s.isEditing);

  useEffect(() => {
    function onBeforeUnload(e: BeforeUnloadEvent) {
      if (!noteDirty && !isEditingPost) return;
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [noteDirty, isEditingPost]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileSidebarOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [setMobileSidebarOpen]);

  useEffect(() => {
    document.body.classList.toggle("mobile-sidebar-open", mobileSidebarOpen);
  }, [mobileSidebarOpen]);

  useEffect(() => {
    document.body.dataset.screen = screen;
  }, [screen]);

  return (
    <div id="app">
      <div
        className="mobile-sidebar-backdrop"
        onClick={() => setMobileSidebarOpen(false)}
        aria-hidden
      />
      <Sidebar onNavigate={() => setMobileSidebarOpen(false)} />
      <div id="main">
        <div className="screen active" id={`screen-${screen}`}>
          {children}
        </div>
      </div>
    </div>
  );
}
