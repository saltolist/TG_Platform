"use client";

import type { InputHTMLAttributes, Ref } from "react";

import { useMobile760 } from "@/shared/lib/hooks/useMobile760";

export function PageHeaderSearchMagnifier({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="11" cy="11" r="6.5" />
      <line x1="15.5" y1="15.5" x2="20" y2="20" />
    </svg>
  );
}

function CloseIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="6.5" y1="6.5" x2="17.5" y2="17.5" />
      <line x1="17.5" y1="6.5" x2="6.5" y2="17.5" />
    </svg>
  );
}

type PageHeaderSearchInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "className"> & {
  className?: string;
  inputRef?: Ref<HTMLInputElement>;
  onDismiss?: () => void;
  dismissAlways?: boolean;
};

export const PAGE_HEADER_SEARCH_INPUT_DISPLAY_NAME = "PageHeaderSearchInput";

export function PageHeaderSearchInput({
  className,
  inputRef,
  onDismiss,
  dismissAlways = false,
  value,
  ...props
}: PageHeaderSearchInputProps) {
  const isMobile = useMobile760();
  const hasText = String(value ?? "").length > 0;
  const showDismiss = !!onDismiss && (dismissAlways || isMobile || hasText);
  const dismissClosesSearch = dismissAlways || isMobile;

  return (
    <div
      className={`page-header-search-field${showDismiss ? " page-header-search-field--dismiss" : ""}`}
    >
      <span className="page-header-search-field-icon" aria-hidden>
        <PageHeaderSearchMagnifier />
      </span>
      <input
        ref={inputRef}
        type="text"
        className={className ?? "page-header-search"}
        value={value}
        {...props}
      />
      {showDismiss ? (
        <button
          type="button"
          className="page-header-search-field-dismiss"
          aria-label={dismissClosesSearch ? "Закрыть поиск" : "Очистить поиск"}
          onClick={onDismiss}
        >
          <CloseIcon size={16} />
        </button>
      ) : null}
    </div>
  );
}

PageHeaderSearchInput.displayName = PAGE_HEADER_SEARCH_INPUT_DISPLAY_NAME;
