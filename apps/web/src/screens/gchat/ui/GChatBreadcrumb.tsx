"use client";

import { Breadcrumb } from "@/shared/ui/breadcrumb";
import {
  buildGChatBreadcrumbTrail,
  type GChatBreadcrumbTrailContext,
} from "@/shared/lib/nav/breadcrumbTrails";

type Props = GChatBreadcrumbTrailContext;

export function GChatBreadcrumb(props: Props) {
  return <Breadcrumb items={buildGChatBreadcrumbTrail(props)} />;
}
