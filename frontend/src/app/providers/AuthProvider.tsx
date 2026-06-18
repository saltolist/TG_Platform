"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { AuthSession } from "@/shared/lib/auth/types";
import { logout as logoutApi } from "@/entities/auth";
import {
  clearGuestSession,
  ensureGuestSession,
  rotateGuestSession,
} from "@/shared/lib/auth/guestSession";
import { clearSession, readSession, writeSession } from "@/shared/lib/auth/session";
import { clearUnauthorizedHandler, setUnauthorizedHandler } from "@/shared/api/httpClient";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { useComposerTargetStore } from "@/app/model/store/composer-target-store";
import { useUiStore } from "@/app/model/store/ui-store";

type AuthContextValue = {
  session: AuthSession | null;
  ready: boolean;
  isPresentationMode: boolean;
  authOverlayOpen: boolean;
  openAuthOverlay: () => void;
  closeAuthOverlay: () => void;
  setSession: (session: AuthSession | null) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSessionState] = useState<AuthSession | null>(null);
  const [ready, setReady] = useState(false);
  const [authOverlayOpen, setAuthOverlayOpen] = useState(false);

  useEffect(() => {
    const userSession = readSession();
    if (userSession) {
      setSessionState(userSession);
    } else {
      ensureGuestSession();
    }
    setReady(true);
  }, []);

  const isPresentationMode = ready && !session;

  const openAuthOverlay = useCallback(() => setAuthOverlayOpen(true), []);
  const closeAuthOverlay = useCallback(() => setAuthOverlayOpen(false), []);

  const setSession = useCallback(
    (next: AuthSession | null) => {
      if (next) {
        clearGuestSession();
        writeSession(next);
        useProfileDraftStore.getState().resetForLogout();
        useComposerTargetStore.getState().resetTargets();
        useUiStore.getState().setMobileSidebarOpen(false);
        setAuthOverlayOpen(false);
      } else {
        clearSession();
      }
      setSessionState(next);
      void queryClient.clear();
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await logoutApi();
    } catch {
      // Client session is cleared even if the request fails.
    }
    clearSession();
    rotateGuestSession();
    setSessionState(null);
    setAuthOverlayOpen(false);
    useProfileDraftStore.getState().resetForLogout();
    useComposerTargetStore.getState().resetTargets();
    void queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      // Guest uses presentation token without a session — 401 must not trigger logout.
      if (!readSession()) return;
      void logout();
    });
    return () => clearUnauthorizedHandler();
  }, [logout]);

  const value = useMemo(
    () => ({
      session,
      ready,
      isPresentationMode,
      authOverlayOpen,
      openAuthOverlay,
      closeAuthOverlay,
      setSession,
      logout,
    }),
    [
      authOverlayOpen,
      closeAuthOverlay,
      isPresentationMode,
      logout,
      openAuthOverlay,
      ready,
      session,
      setSession,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}
