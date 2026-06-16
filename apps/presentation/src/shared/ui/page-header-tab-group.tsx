"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/shared/lib/utils";

export type PageHeaderTabOption<T extends string = string> = {
  value: T;
  label: string;
};

type PageHeaderControlProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean;
};

export function PageHeaderControl({ active, className, type = "button", ...props }: PageHeaderControlProps) {
  return (
    <button
      type={type}
      className={cn("page-header-control", active && "active", className)}
      {...props}
    />
  );
}

type PageHeaderTabListProps<T extends string> = {
  value: T;
  options: readonly PageHeaderTabOption<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
  wrap?: boolean;
};

export function PageHeaderTabList<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  className,
  wrap = false,
}: PageHeaderTabListProps<T>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "page-header-tablist page-header-toolbar--desktop",
        wrap && "page-header-tablist--wrap",
        className,
      )}
    >
      {options.map((option) => {
        const active = value === option.value;
        return (
          <PageHeaderControl
            key={option.value}
            role="tab"
            aria-selected={active}
            active={active}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </PageHeaderControl>
        );
      })}
    </div>
  );
}

/** Desktop-only tab row (e.g. feed card width toggles hidden on mobile via toolbar class). */
export function PageHeaderTabListDesktop({
  children,
  ariaLabel,
  className,
}: {
  children: ReactNode;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn("page-header-tablist page-header-toolbar--desktop", className)}
    >
      {children}
    </div>
  );
}
