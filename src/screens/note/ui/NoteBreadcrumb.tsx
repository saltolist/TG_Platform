"use client";

import { Breadcrumb } from "@/shared/ui/breadcrumb";
import {
  buildNoteBreadcrumbTrail,
  type NoteBreadcrumbTrailContext,
} from "@/shared/lib/nav/breadcrumbTrails";

type Props = NoteBreadcrumbTrailContext;

export default function NoteBreadcrumb(props: Props) {
  return <Breadcrumb items={buildNoteBreadcrumbTrail(props)} />;
}
