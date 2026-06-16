"use client";

import { useRouter } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { screenToHref } from "@/shared/lib/routes";
import type { BreadcrumbItem } from "@/shared/ui/breadcrumb";
import type { ScreenId } from "@/shared/types";
import {
  buildExpandableSearchContent,
  measureSearchSpanPx,
  resolveDesktopSearchToggleAnchor,
  resolveSearchSpanRightAnchor,
} from "@/widgets/page-header/lib/pageHeaderSearchUtils";
import {
  clearProfilePageHeaderBreakpoints,
  syncProfilePageHeaderBreakpoints,
} from "@/widgets/page-header/model/useProfilePageHeaderSync";
import type { PageHeaderOverflowItem } from "@/widgets/page-header/ui/page-header-overflow";

export type PageHeaderProps = {
  title?: ReactNode;
  left?: ReactNode;
  breadcrumbs?: BreadcrumbItem[];
  backTo?: ScreenId;
  onBack?: () => void;
  backLabel?: string;
  search?: ReactNode;
  center?: ReactNode;
  mobileSelect?: ReactNode;
  actions?: ReactNode;
  overflowItems?: PageHeaderOverflowItem[];
  compactSearchAtWidth?: number;
  compactSearchOverlay?: boolean;
  profileBreakpoints?: boolean;
  className?: string;
  showBack?: boolean;
};

export function usePageHeader({
  title,
  left,
  backTo,
  onBack,
  backLabel = "Назад",
  search,
  center,
  mobileSelect,
  actions,
  overflowItems,
  compactSearchAtWidth,
  compactSearchOverlay = false,
  /** @deprecated Breakpoints sync on every PageHeader (legacy parity). Prop kept for call sites. */
  profileBreakpoints: _profileBreakpoints = false,
  className,
  showBack,
}: PageHeaderProps) {
  const router = useRouter();
  const handleBack =
    showBack === false
      ? undefined
      : (onBack ?? (backTo ? () => router.push(screenToHref(backTo)) : undefined));

  const isMobile = useMobile760();
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
  const [headerWidth, setHeaderWidth] = useState(0);
  const headerRef = useRef<HTMLElement>(null);
  const mobileSearchLeftRef = useRef<HTMLDivElement>(null);
  const menuBtnRef = useRef<HTMLButtonElement>(null);
  const mobileSelectWrapRef = useRef<HTMLDivElement>(null);
  const mobileSearchWrapRef = useRef<HTMLDivElement>(null);
  const overflowWrapRef = useRef<HTMLDivElement>(null);
  const headerRightRef = useRef<HTMLDivElement>(null);
  const searchToggleAnchorRef = useRef<HTMLElement>(null);
  const mobileSearchInputRef = useRef<HTMLInputElement | null>(null);

  const compactSearch =
    !isMobile &&
    !!search &&
    (compactSearchOverlay ||
      (compactSearchAtWidth != null &&
        headerWidth > 0 &&
        headerWidth <= compactSearchAtWidth));
  const mobileOverlaySearch = isMobile;
  const searchOverlayMode =
    compactSearchOverlay && (isMobile || compactSearch);
  /** Desktop: поле в правой колонке, растёт влево (пост overlay, лента ≤ compactSearchAtWidth). */
  const desktopInlineSearch =
    compactSearch &&
    !mobileOverlaySearch &&
    (compactSearchOverlay || compactSearchAtWidth != null);

  useLayoutEffect(() => {
    const el = headerRef.current;
    if (!el) return;

    const sync = () => {
      const w = Math.round(el.getBoundingClientRect().width);
      if (compactSearchAtWidth != null) {
        setHeaderWidth(w);
      }
      document.documentElement.style.setProperty("--page-header-w", `${w}px`);
      document.documentElement.style.setProperty("--page-header-w-num", String(w));
      syncProfilePageHeaderBreakpoints(w, isMobile);
    };

    const observer = new ResizeObserver(sync);
    observer.observe(el);
    sync();

    return () => {
      observer.disconnect();
      if (compactSearchAtWidth != null) {
        setHeaderWidth(0);
      }
      clearProfilePageHeaderBreakpoints();
      document.documentElement.style.removeProperty("--page-header-w");
      document.documentElement.style.removeProperty("--page-header-w-num");
    };
  }, [compactSearchAtWidth, isMobile]);

  useEffect(() => {
    if (!mobileOverlaySearch && !compactSearch) {
      setMobileSearchOpen(false);
    }
  }, [mobileOverlaySearch, compactSearch]);

  useLayoutEffect(() => {
    if (!mobileSearchOpen || (!mobileOverlaySearch && !compactSearch)) return;
    const wrap = mobileSearchWrapRef.current;
    if (!wrap) return;
    const input = wrap.querySelector<HTMLInputElement>("input, textarea");
    mobileSearchInputRef.current = input;
    input?.focus();
    if (input && "setSelectionRange" in input) {
      try {
        const len = input.value?.length ?? 0;
        input.setSelectionRange(len, len);
      } catch {
        // ignore
      }
    }
  }, [mobileSearchOpen, mobileOverlaySearch, compactSearch]);

  const hasTrailingOverflow = overflowItems != null && overflowItems.length > 0;
  const hasMobileSearchTrailing = !!mobileSelect || hasTrailingOverflow;

  const needsSearchSpan =
    mobileSearchOpen &&
    !desktopInlineSearch &&
    (searchOverlayMode || (mobileOverlaySearch && hasMobileSearchTrailing));

  useLayoutEffect(() => {
    if (!needsSearchSpan) return;
    const header = headerRef.current;
    const left = mobileSearchLeftRef.current;
    const rightColumn = headerRightRef.current;
    if (!header || !left || !rightColumn) return;

    const updateSearchSpan = () => {
      const headerStyle = getComputedStyle(header);
      const padL = parseFloat(headerStyle.paddingLeft) || 0;
      const padR = parseFloat(headerStyle.paddingRight) || 0;
      const desktopPostOverlay = searchOverlayMode && !mobileOverlaySearch;
      const overflowWrap = overflowWrapRef.current;
      const searchToggleAnchor = desktopPostOverlay
        ? resolveDesktopSearchToggleAnchor(rightColumn, searchToggleAnchorRef.current)
        : null;
      const rightAnchor = resolveSearchSpanRightAnchor(
        rightColumn,
        overflowWrap,
        desktopPostOverlay,
      );
      const span = measureSearchSpanPx({
        header,
        left,
        rightColumn,
        rightAnchor,
        padL,
        padR,
        desktopPostOverlay,
        searchToggleAnchor,
      });
      header.style.setProperty("--page-header-search-span-left", `${span.left}px`);
      header.style.setProperty("--page-header-search-span-right", `${span.right}px`);
      header.style.removeProperty("--page-header-search-field-right-offset");
    };

    updateSearchSpan();
    const observer = new ResizeObserver(updateSearchSpan);
    observer.observe(header);
    observer.observe(left);
    observer.observe(rightColumn);
    const overflowWrap = overflowWrapRef.current;
    if (overflowWrap) observer.observe(overflowWrap);
    const searchToggleAnchor = searchToggleAnchorRef.current;
    if (searchToggleAnchor) observer.observe(searchToggleAnchor);
    const actionsDesktop = rightColumn.querySelector(".page-header-actions--desktop");
    if (actionsDesktop) observer.observe(actionsDesktop);
    window.addEventListener("resize", updateSearchSpan);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateSearchSpan);
    };
  }, [needsSearchSpan, mobileSearchOpen, searchOverlayMode, mobileOverlaySearch, hasMobileSearchTrailing]);

  const showSearchToggle = (mobileOverlaySearch || compactSearch) && !!search;
  const expandableSearchContent =
    mobileSearchOpen && search
      ? buildExpandableSearchContent(search, () => setMobileSearchOpen(false))
      : null;

  const hasTrailingToolbar =
    !!mobileSelect || (overflowItems != null && overflowItems.length > 0);
  const showMobileRight =
    isMobile &&
    ((showSearchToggle && !mobileSearchOpen) ||
      hasTrailingToolbar ||
      (mobileSearchOpen && hasTrailingToolbar));

  const trailingDesktopSelect =
    !isMobile && !!mobileSelect && compactSearchAtWidth == null;
  const showCompactToolbarSelect = compactSearch && !!mobileSelect;
  /** Лента: кластер всегда при compact; пост — только при раскрытом inline-поиске. */
  const clusterDesktopActions =
    (desktopInlineSearch && mobileSearchOpen) ||
    (compactSearch && !isMobile && compactSearchAtWidth != null);

  const headerClassName = [
    "page-header",
    className,
    mobileSearchOpen ? "page-header--search-open" : "",
    mobileSearchOpen && mobileOverlaySearch && hasMobileSearchTrailing
      ? "page-header--has-mobile-select"
      : "",
    trailingDesktopSelect ? "page-header--trailing-select" : "",
    compactSearch ? "page-header--compact-search" : "",
    searchOverlayMode ? "page-header--post-search-overlay" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return {
    title,
    left,
    backLabel,
    search,
    center,
    mobileSelect,
    actions,
    overflowItems,
    headerRef,
    mobileSearchLeftRef,
    menuBtnRef,
    mobileSelectWrapRef,
    mobileSearchWrapRef,
    overflowWrapRef,
    headerRightRef,
    searchToggleAnchorRef,
    compactSearchOverlay,
    searchOverlayMode,
    desktopInlineSearch,
    headerClassName,
    isMobile,
    mobileSearchOpen,
    setMobileSearchOpen,
    compactSearch,
    mobileOverlaySearch,
    showSearchToggle,
    expandableSearchContent,
    hasTrailingToolbar,
    showMobileRight,
    trailingDesktopSelect,
    showCompactToolbarSelect,
    clusterDesktopActions,
    handleBack,
  };
}
