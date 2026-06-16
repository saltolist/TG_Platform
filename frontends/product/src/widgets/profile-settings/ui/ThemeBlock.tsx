"use client";

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useTheme } from "next-themes";

import { useMediaQuery } from "@/shared/lib/hooks/useMediaQuery";
import type { ThemeMode } from "@/shared/types";

const OPTIONS: {
  id: ThemeMode;
  label: string;
  Icon: LucideIcon;
  hint: string;
}[] = [
  { id: "light", label: "Светлая", Icon: Sun, hint: "Всегда светлая тема" },
  { id: "system", label: "Системная", Icon: Monitor, hint: "Следует за настройками ОС" },
  { id: "dark", label: "Тёмная", Icon: Moon, hint: "Всегда тёмная тема" },
];

export default function ThemeBlock() {
  const { theme, setTheme } = useTheme();
  const activeTheme = (theme ?? "system") as ThemeMode;
  const isCompact = useMediaQuery("(max-width: 360px)");

  return (
    <div className="profile-section">
      <div className="profile-section-title">Тема</div>
      <div className="theme-switch" role="radiogroup" aria-label="Выбор темы">
        {OPTIONS.map((opt) => {
          const active = activeTheme === opt.id;
          const label = opt.id === "system" && isCompact ? "Авто" : opt.label;
          const { Icon } = opt;
          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={active}
              title={opt.hint}
              className={`theme-switch-btn${active ? " active" : ""}`}
              onClick={() => setTheme(opt.id)}
            >
              <span className="theme-switch-icon" aria-hidden>
                <Icon size={15} strokeWidth={2} />
              </span>
              <span>{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
