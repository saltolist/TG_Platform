import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";

import { PRESENTATION_GUEST_TOKEN } from "@/shared/lib/auth/constants";
import { initialAiProfileConfig } from "@/shared/data/seed-data";
import { resetAccountRegistry } from "./accountRegistry";
import { handlers } from "./handlers";

const server = setupServer(...handlers);

function authHeaders(token = PRESENTATION_GUEST_TOKEN): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  resetAccountRegistry();
});
afterAll(() => server.close());

describe("profile/ai MSW handlers", () => {
  it("GET returns presentation ai profile for guest token", async () => {
    const res = await fetch("http://localhost/api/v1/profile/ai/", {
      headers: { Authorization: `Bearer ${PRESENTATION_GUEST_TOKEN}` },
    });

    expect(res.status).toBe(200);
    const body = (await res.json()) as { llmModels: unknown[] };
    expect(body.llmModels.length).toBeGreaterThan(0);
  });

  it("PUT updates presentation ai profile for guest token", async () => {
    const payload = {
      ...initialAiProfileConfig,
      systemPrompt: "updated prompt",
    };

    const res = await fetch("http://localhost/api/v1/profile/ai/", {
      method: "PUT",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    });

    expect(res.status).toBe(200);
    const body = (await res.json()) as { systemPrompt: string };
    expect(body.systemPrompt).toBe("updated prompt");

    const again = await fetch("http://localhost/api/v1/profile/ai/", {
      headers: { Authorization: `Bearer ${PRESENTATION_GUEST_TOKEN}` },
    });
    const stored = (await again.json()) as { systemPrompt: string };
    expect(stored.systemPrompt).toBe("updated prompt");
  });

  it("PUT without auth returns 401", async () => {
    const res = await fetch("http://localhost/api/v1/profile/ai/", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(initialAiProfileConfig),
    });

    expect(res.status).toBe(401);
  });
});
