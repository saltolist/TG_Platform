"use client";

import type { ReactNode, RefObject } from "react";

import { Breadcrumb, type BreadcrumbItem } from "@/shared/ui/breadcrumb";
import { PageHeaderMenuButton } from "@/widgets/page-header/ui/page-header-menu-button";

export type PageHeaderLeftProps = {
  leftRef?: RefObject<HTMLDivElement | null>;
  menuBtnRef?: RefObject<HTMLButtonElement | null>;
  title?: ReactNode;
  breadcrumbs?: BreadcrumbItem[];
  left?: ReactNode;
  showTitle?: boolean;
  showLeft?: boolean;
};

export function PageHeaderLeft({
  leftRef,
  menuBtnRef,
  title,
  breadcrumbs,
  left,
  showTitle = true,
  showLeft = true,
}: PageHeaderLeftProps) {
  const hasBreadcrumbs = breadcrumbs != null && breadcrumbs.length > 0;

  return (
    <div className="page-header-left" ref={leftRef}>
      <PageHeaderMenuButton ref={menuBtnRef} />
      {showTitle && !left && hasBreadcrumbs ? (
        <Breadcrumb items={breadcrumbs} className="breadcrumb" />
      ) : showTitle && !left && title ? (
        <h2>{title}</h2>
      ) : null}
      {showLeft ? left : null}
    </div>
  );
}
