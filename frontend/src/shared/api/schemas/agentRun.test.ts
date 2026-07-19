import { describe, expect, it } from "vitest";

import { messageContextManifestSchema, plannerStepSchema } from "./agentRun";

describe("plannerStepSchema", () => {
  it("accepts a full planner decision", () => {
    const parsed = plannerStepSchema.parse({
      step: 1,
      observations: ["пост 721 notes=1"],
      reasoning: "нужен текст заметки",
      gap: "note content missing",
      tool: "OpenNote",
      args: { note_id: "n1" },
    });
    expect(parsed.tool).toBe("OpenNote");
    expect(parsed.observations).toEqual(["пост 721 notes=1"]);
  });

  it("accepts an empty observations list on the first step", () => {
    const parsed = plannerStepSchema.parse({
      step: 1,
      observations: [],
      reasoning: "старт",
      gap: "",
      tool: "SearchNodes",
      args: {},
    });
    expect(parsed.observations).toEqual([]);
  });

  it("accepts an optional repair_hint", () => {
    const parsed = plannerStepSchema.parse({
      step: 2,
      observations: ["выдуманный факт"],
      reasoning: "...",
      gap: "...",
      tool: "OpenNote",
      args: {},
      repair_hint: "cosmetic_observations:выдуманный факт",
    });
    expect(parsed.repair_hint).toBe("cosmetic_observations:выдуманный факт");
  });

  it("rejects a payload missing the tool field", () => {
    const result = plannerStepSchema.safeParse({
      step: 1,
      observations: [],
      reasoning: "...",
      gap: "...",
      args: {},
    });
    expect(result.success).toBe(false);
  });
});

describe("messageContextManifestSchema", () => {
  const manifest = {
    schema: "workspace.message-context/v1",
    message_id: "message-1",
    run_id: "run-1",
    source_turn_id: "run-1",
    context_refs: [{ ref: "post:p1", kind: "post", provenance: "exact", route: "/post/p1/" }],
    cited_evidence: ["/post/p1/"],
    artifacts: [],
    stale_refs: [],
  };

  it("accepts v1 and preserves source refs", () => {
    expect(messageContextManifestSchema.parse(manifest).context_refs?.[0]?.ref).toBe("post:p1");
  });

  it("rejects unknown manifest versions", () => {
    expect(messageContextManifestSchema.safeParse({ ...manifest, schema: "workspace.message-context/v2" }).success).toBe(false);
  });
});
