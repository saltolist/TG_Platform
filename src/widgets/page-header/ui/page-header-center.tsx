"use client";

import type { ReactNode, RefObject } from "react";

export type PageHeaderCenterProps = {
  mobileOverlaySearch?: boolean;
  compactSearch?: boolean;
  compactSearchOverlay?: boolean;
  inlineDesktopSearch?: boolean;
  mobileSearchOpen?: boolean;
  expandableSearchContent?: ReactNode | null;
  mobileSearchWrapRef?: RefObject<HTMLDivElement | null>;
  center?: ReactNode;
  search?: ReactNode;
};

export function PageHeaderCenter({
  mobileOverlaySearch = false,
  compactSearch = false,
  compactSearchOverlay = false,
  inlineDesktopSearch = false,
  mobileSearchOpen = false,
  expandableSearchContent = null,
  mobileSearchWrapRef,
  center,
  search,
}: PageHeaderCenterProps) {
  if (
    mobileSearchOpen &&
    expandableSearchContent &&
    !inlineDesktopSearch &&
    (mobileOverlaySearch || (compactSearch && compactSearchOverlay))
  ) {
    return (
      <>
        <div className="page-header-search-expand" ref={mobileSearchWrapRef}>
          {expandableSearchContent}
        </div>
        <div className="page-header-search-spacer" aria-hidden />
      </>
    );
  }

  if (compactSearch && mobileSearchOpen && expandableSearchContent && !inlineDesktopSearch) {
    return (
      <div
        className="page-header-center page-header-compact-search-field"
        ref={mobileSearchWrapRef}
      >
        {expandableSearchContent}
      </div>
    );
  }

  return (
    <div className="page-header-center" aria-hidden={mobileOverlaySearch ? true : undefined}>
      {center && !mobileOverlaySearch && !compactSearch ? center : null}
      {search && !mobileOverlaySearch && !compactSearch ? search : null}
    </div>
  );
}
