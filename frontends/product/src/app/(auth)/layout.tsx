import type { ReactNode } from "react";
import "@/app/styles/shell-auth.css";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-layout">
      <div className="auth-layout-inner">{children}</div>
    </div>
  );
}
