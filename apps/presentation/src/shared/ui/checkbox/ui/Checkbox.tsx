"use client";

import type { InputHTMLAttributes } from "react";

/**
 * Checkbox with hover-preview suppression after click until mouse leaves row.
 */
export default function Checkbox({
  onChange,
  onMouseLeave,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      className={className ?? "profile-checkbox"}
      {...props}
      onChange={(e) => {
        e.target.classList.add("profile-checkbox--suppress-hover");
        onChange?.(e);
      }}
      onMouseLeave={(e) => {
        const related = e.relatedTarget as Node | null;
        const row = e.currentTarget.closest("label");
        if (row && related && row.contains(related)) return;
        e.currentTarget.classList.remove("profile-checkbox--suppress-hover");
        onMouseLeave?.(e);
      }}
    />
  );
}
