"use client";

import { usePageHeader, type PageHeaderProps } from "@/widgets/page-header/model/usePageHeader";
import { PageHeaderCenter } from "@/widgets/page-header/ui/page-header-center";
import { PageHeaderLeft } from "@/widgets/page-header/ui/page-header-left";
import { PageHeaderRight } from "@/widgets/page-header/ui/page-header-right";

export type { PageHeaderProps };

export function PageHeader(props: PageHeaderProps) {
  const {
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
  } = usePageHeader(props);

  return (
    <header ref={headerRef} className={headerClassName}>
      <PageHeaderLeft
        leftRef={mobileSearchLeftRef}
        menuBtnRef={menuBtnRef}
        title={title}
        left={left}
        breadcrumbs={props.breadcrumbs}
        showTitle={!mobileSearchOpen || !searchOverlayMode || desktopInlineSearch}
        showLeft={!(mobileSearchOpen && searchOverlayMode && !desktopInlineSearch)}
      />
      <PageHeaderCenter
        mobileOverlaySearch={mobileOverlaySearch}
        compactSearch={compactSearch}
        compactSearchOverlay={compactSearchOverlay}
        inlineDesktopSearch={desktopInlineSearch}
        mobileSearchOpen={mobileSearchOpen}
        expandableSearchContent={expandableSearchContent}
        mobileSearchWrapRef={mobileSearchWrapRef}
        center={center}
        search={search}
      />
      <PageHeaderRight
        isMobile={isMobile}
        showMobileRight={showMobileRight}
        compactSearch={compactSearch}
        inlineDesktopSearch={desktopInlineSearch}
        expandableSearchContent={expandableSearchContent}
        mobileSearchWrapRef={mobileSearchWrapRef}
        showSearchToggle={showSearchToggle}
        mobileSearchOpen={mobileSearchOpen}
        setMobileSearchOpen={setMobileSearchOpen}
        showCompactToolbarSelect={showCompactToolbarSelect}
        trailingDesktopSelect={trailingDesktopSelect}
        mobileSelect={mobileSelect}
        mobileSelectWrapRef={mobileSelectWrapRef}
        handleBack={handleBack}
        backLabel={backLabel}
        actions={actions}
        overflowItems={overflowItems}
        overflowWrapRef={overflowWrapRef}
        headerRightRef={headerRightRef}
        searchToggleAnchorRef={searchToggleAnchorRef}
        hasTrailingToolbar={hasTrailingToolbar}
        clusterDesktopActions={clusterDesktopActions}
      />
    </header>
  );
}
