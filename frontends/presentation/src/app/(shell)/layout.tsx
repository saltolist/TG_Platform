import { Suspense } from "react";

import { ComposerNavBridge } from "@/widgets/composer/ui/ComposerNavBridge";
import { AppShell, ContentAdaptSync, RouteSync } from "@/widgets/app-shell";
import { AccountDataScopeSync } from "@/app/providers/AccountDataScopeSync";
import { ShellQueryBootstrap } from "@/app/providers/ShellQueryBootstrap";
import { AuthGuard } from "@/features/auth-guard";
import { AuthOverlay } from "@/screens/_ui/AuthOverlay";
import { ProfileHydrator } from "@/widgets/profile-settings/ui/ProfileHydrator";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <ShellQueryBootstrap />
      <AccountDataScopeSync />
      <ProfileHydrator />
      <AppShell>
        <ContentAdaptSync />
        <Suspense fallback={null}>
          <RouteSync />
          <ComposerNavBridge />
        </Suspense>
        {children}
      </AppShell>
      <AuthOverlay />
    </AuthGuard>
  );
}
