"use client";

import type { ReactNode, Ref, RefObject } from "react";

import { BackButton } from "@/shared/ui/back-button";
import { PageHeaderSearchMagnifier } from "@/widgets/page-header/ui/PageHeaderSearchInput";
import {
  PageHeaderOverflow,
  type PageHeaderOverflowItem,
} from "@/widgets/page-header/ui/page-header-overflow";

export type PageHeaderRightProps = {
  isMobile?: boolean;
  showMobileRight?: boolean;
  compactSearch?: boolean;
  inlineDesktopSearch?: boolean;
  expandableSearchContent?: ReactNode | null;
  mobileSearchWrapRef?: RefObject<HTMLDivElement | null>;
  showSearchToggle?: boolean;
  mobileSearchOpen?: boolean;
  setMobileSearchOpen?: (open: boolean) => void;
  showCompactToolbarSelect?: boolean;
  trailingDesktopSelect?: boolean;
  mobileSelect?: ReactNode;
  mobileSelectWrapRef?: RefObject<HTMLDivElement | null>;
  handleBack?: () => void;
  backLabel?: string;
  actions?: ReactNode;
  overflowItems?: PageHeaderOverflowItem[];
  overflowWrapRef?: Ref<HTMLDivElement>;
  headerRightRef?: Ref<HTMLDivElement>;
  searchToggleAnchorRef?: Ref<HTMLElement>;
  hasTrailingToolbar?: boolean;
  clusterDesktopActions?: boolean;
};

export function PageHeaderRight({
  isMobile = false,
  showMobileRight = false,
  compactSearch = false,
  inlineDesktopSearch = false,
  expandableSearchContent = null,
  mobileSearchWrapRef,
  showSearchToggle = false,
  mobileSearchOpen = false,
  setMobileSearchOpen,
  showCompactToolbarSelect = false,
  trailingDesktopSelect = false,
  mobileSelect,
  mobileSelectWrapRef,
  handleBack,
  backLabel = "Назад",
  actions,
  overflowItems,
  overflowWrapRef,
  headerRightRef,
  searchToggleAnchorRef,
  hasTrailingToolbar = false,
  clusterDesktopActions = false,
}: PageHeaderRightProps) {
  if (isMobile && !showMobileRight) return null;

  const desktopTrailing = (
    <>
      {showCompactToolbarSelect ? (
        <div
          ref={mobileSelectWrapRef}
          className="page-header-toolbar-slot page-header-toolbar--desktop-select"
        >
          {mobileSelect}
        </div>
      ) : null}
      {trailingDesktopSelect && mobileSelect ? (
        <div className="page-header-toolbar-slot page-header-toolbar--desktop-select">
          {mobileSelect}
        </div>
      ) : null}
      {handleBack ? <BackButton onClick={handleBack} label={backLabel} /> : null}
      {actions}
      {overflowItems && overflowItems.length > 0 ? (
        <div ref={overflowWrapRef}>
          <PageHeaderOverflow items={overflowItems} />
        </div>
      ) : null}
    </>
  );

  const desktopInlineSearchOpen =
    inlineDesktopSearch && mobileSearchOpen && !!expandableSearchContent;

  return (
    <div
      ref={headerRightRef}
      className={`page-header-right${showMobileRight || compactSearch ? " page-header-right--mobile" : ""}`}
    >
      {!isMobile ? (
        <div className="page-header-actions--desktop">
          {desktopInlineSearchOpen ? (
            <div className="page-header-search-inline" ref={mobileSearchWrapRef}>
              {expandableSearchContent}
            </div>
          ) : compactSearch && showSearchToggle ? (
            mobileSearchOpen ? (
              <span
                ref={searchToggleAnchorRef}
                className="page-header-search-toggle-slot"
                aria-hidden
              />
            ) : (
              <button
                ref={searchToggleAnchorRef as Ref<HTMLButtonElement>}
                type="button"
                className="page-header-search-toggle"
                aria-label="Поиск"
                aria-expanded={mobileSearchOpen}
                onClick={() => setMobileSearchOpen?.(true)}
              >
                <PageHeaderSearchMagnifier size={20} />
              </button>
            )
          ) : showSearchToggle && !mobileSearchOpen ? (
            <button
              ref={searchToggleAnchorRef as Ref<HTMLButtonElement>}
              type="button"
              className="page-header-search-toggle"
              aria-label="Поиск"
              aria-expanded={mobileSearchOpen}
              onClick={() => setMobileSearchOpen?.(true)}
            >
              <PageHeaderSearchMagnifier size={20} />
            </button>
          ) : null}
          {clusterDesktopActions ? (
            <div className="page-header-actions-cluster">{desktopTrailing}</div>
          ) : (
            desktopTrailing
          )}
        </div>
      ) : null}
      {showMobileRight ? (
        <>
          {showSearchToggle ? (
            mobileSearchOpen ? (
              hasTrailingToolbar ? (
                <span className="page-header-search-toggle-slot" aria-hidden />
              ) : null
            ) : (
              <button
                type="button"
                className="page-header-search-toggle"
                aria-label="Поиск"
                aria-expanded={mobileSearchOpen}
                onClick={() => setMobileSearchOpen?.(true)}
              >
                <PageHeaderSearchMagnifier size={20} />
              </button>
            )
          ) : null}
          {mobileSelect ? (
            <div
              ref={isMobile ? mobileSelectWrapRef : undefined}
              className="page-header-toolbar-slot page-header-toolbar--mobile"
            >
              {mobileSelect}
            </div>
          ) : null}
          {overflowItems && overflowItems.length > 0 ? (
            <div ref={overflowWrapRef}>
              <PageHeaderOverflow className="page-header-actions--mobile" items={overflowItems} />
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
