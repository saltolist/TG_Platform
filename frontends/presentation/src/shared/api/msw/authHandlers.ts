import { http, HttpResponse } from "msw";
import type { AuthSession } from "@/shared/lib/auth/types";
import {
  DEMO_ACCOUNT_ID,
  DEMO_EMAIL,
  DEMO_EMAIL_CODE,
  DEMO_PASSWORD,
} from "@/shared/lib/auth/constants";
import { apiV1MswPath } from "@/shared/config/basePath";
import {
  createAuthToken,
  createFreshAccount,
  pendingRegistrations,
  resetAccountRegistry,
  resetDemoFullAccount,
} from "./accountRegistry";

function unauthorized() {
  return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
}

function badRequest(message: string) {
  return HttpResponse.json({ error: message }, { status: 400 });
}

function createSessionResponse(accountId: string, email: string): AuthSession {
  return {
    token: createAuthToken(accountId),
    accountId,
    email,
    createdAt: new Date().toISOString(),
  };
}

export const authHandlers = [
  http.post(apiV1MswPath("auth/login"), async ({ request }) => {
    const body = (await request.json()) as { email?: string; password?: string };
    const email = body.email?.trim().toLowerCase() ?? "";
    const password = body.password ?? "";

    if (email !== DEMO_EMAIL.toLowerCase() || password !== DEMO_PASSWORD) {
      return HttpResponse.json({ error: "Неверный email или пароль" }, { status: 401 });
    }

    resetDemoFullAccount();
    return HttpResponse.json(createSessionResponse(DEMO_ACCOUNT_ID, DEMO_EMAIL));
  }),

  http.post(apiV1MswPath("auth/logout"), () => {
    resetAccountRegistry();
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(apiV1MswPath("auth/register/send-code"), async ({ request }) => {
    const body = (await request.json()) as { email?: string; password?: string };
    const email = body.email?.trim().toLowerCase() ?? "";
    const password = body.password ?? "";

    if (!email || !password) {
      return badRequest("Укажите email и пароль");
    }
    if (email === DEMO_EMAIL.toLowerCase()) {
      return badRequest("Этот email зарезервирован для демо-входа");
    }

    pendingRegistrations.set(email, { password, code: DEMO_EMAIL_CODE });
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(apiV1MswPath("auth/register/verify"), async ({ request }) => {
    const body = (await request.json()) as { email?: string; code?: string };
    const email = body.email?.trim().toLowerCase() ?? "";
    const code = body.code?.trim() ?? "";

    const pending = pendingRegistrations.get(email);
    if (!pending) {
      return badRequest("Сначала запросите код на почту");
    }
    if (code !== pending.code) {
      return badRequest("Неверный код");
    }

    pendingRegistrations.delete(email);
    const accountId = createFreshAccount();
    return HttpResponse.json(createSessionResponse(accountId, email));
  }),

  http.post(apiV1MswPath("auth/forgot-password/send-code"), async ({ request }) => {
    const body = (await request.json()) as { email?: string };
    const email = body.email?.trim().toLowerCase() ?? "";
    if (!email) return badRequest("Укажите email");
    if (email !== DEMO_EMAIL.toLowerCase()) {
      return badRequest("Для демо восстановление доступно только для demo@mail.ru");
    }
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(apiV1MswPath("auth/forgot-password/reset"), async ({ request }) => {
    const body = (await request.json()) as { email?: string; code?: string; password?: string };
    const email = body.email?.trim().toLowerCase() ?? "";
    const code = body.code?.trim() ?? "";

    if (email !== DEMO_EMAIL.toLowerCase()) {
      return badRequest("Для демо восстановление доступно только для demo@mail.ru");
    }
    if (code !== DEMO_EMAIL_CODE) {
      return badRequest("Неверный код");
    }
    if (!body.password?.trim()) {
      return badRequest("Укажите новый пароль");
    }
    return new HttpResponse(null, { status: 204 });
  }),
];
