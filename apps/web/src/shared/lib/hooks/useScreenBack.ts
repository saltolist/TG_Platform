import { canAppNavigateBack } from "@/shared/lib/appNavStack";
import { getParentPath, routes } from "@/shared/lib/routes";

export type ScreenBackAction =
  | { type: "back" }
  | { type: "push"; href: string };

/** Back via in-app visit stack when possible; otherwise logical parent path. */
export function resolveScreenBackAction(
  pathname: string,
  searchParams?: URLSearchParams | null,
): ScreenBackAction {
  const params = searchParams ?? new URLSearchParams();
  if (canAppNavigateBack(pathname, params)) {
    return { type: "back" };
  }
  const parent = getParentPath(pathname);
  return { type: "push", href: parent ?? routes.home() };
}
