import type { ReactNode } from "react";

type ScreenShellProps = {
  header: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** When set, replaces default `.screen-body` wrapper (e.g. `notes-page`, `chats-page`). */
  bodyClassName?: string;
  bodyId?: string;
};

export function ScreenShell({ header, children, footer, bodyClassName, bodyId }: ScreenShellProps) {
  return (
    <>
      {header}
      <div id={bodyId} className={bodyClassName ?? "screen-body"}>
        {children}
      </div>
      {footer}
    </>
  );
}
