"use client";

type SidebarBrandProps = {
  onClick: () => void;
  showLabel?: boolean;
};

export function SidebarBrand({ onClick, showLabel = true }: SidebarBrandProps) {
  if (!showLabel) {
    return (
      <button
        type="button"
        className="mx-auto flex size-9 items-center justify-center rounded-lg text-base transition-colors hover:bg-sidebar-accent/60"
        onClick={onClick}
        aria-label="Развернуть панель"
        title="Развернуть панель"
      >
        <span aria-hidden>✦</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1 py-1 text-left transition-colors hover:bg-sidebar-accent/60"
      title="TG Platform — на главную"
      aria-label="TG Platform — на главную"
    >
      <span className="text-base leading-none text-primary" aria-hidden>
        ✦
      </span>
      <span className="truncate text-sm font-semibold">TG Platform</span>
    </button>
  );
}
