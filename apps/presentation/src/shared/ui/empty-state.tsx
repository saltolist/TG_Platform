"use client";

import type { ReactNode } from "react";

import { cn } from "@/shared/lib/utils";

type EmptyStateProps = {
  icon?: ReactNode;
  message: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ icon, message, action, className }: EmptyStateProps) {
  return (
    <div className={cn("screen-placeholder", className)}>
      {icon}
      <p>{message}</p>
      {action}
    </div>
  );
}
