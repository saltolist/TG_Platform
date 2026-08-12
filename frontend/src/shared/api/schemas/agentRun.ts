import { z } from "zod";

export const agentRunStatusSchema = z.enum([
  "running",
  "interrupted",
  "completed",
  "failed",
  "cancelled",
]);

export const agentProposalSchema = z.object({
  id: z.string(),
  command: z.string(),
  payload_hash: z.string(),
  warnings: z.array(z.string()).optional(),
  preview: z.record(z.string(), z.unknown()).optional(),
  resource_version: z.string().nullable().optional(),
});

export const agentMediaJobSchema = z.object({
  id: z.string(),
  status: z.string(),
  stage: z.string().nullable().optional(),
  progress: z.number(),
  reserved_cost: z.number().nullable().optional(),
  preview_url: z.string().optional(),
});

export const agentEventSchema = z.object({
  sequence: z.number(),
  type: z.string(),
  payload: z.record(z.string(), z.unknown()),
});

// agent-runtime-sprints §3.1/§3.3: the research planner's decision shape,
// thought fields before the tool ({observations, reasoning, gap, tool, args}).
// Emitted as the "planner_step" agent event so the UI can render steps 1..N.
export const plannerStepSchema = z.object({
  step: z.number(),
  observations: z.array(z.string()),
  reasoning: z.string(),
  gap: z.string(),
  tool: z.string(),
  args: z.record(z.string(), z.unknown()),
  repair_hint: z.string().optional(),
});

export const agentSsePayloadSchema = z.object({
  agent: agentEventSchema.optional(),
  text: z.string().optional(),
  meta: z.record(z.string(), z.unknown()).optional(),
});

export const messageContextRefSchema = z.object({
  ref: z.string(),
  kind: z.string(),
  title: z.string().nullable().optional(),
  summary: z.string().nullable().optional(),
  revision: z.number().nullable().optional(),
  source_turn_id: z.string().nullable().optional(),
  role: z.string().optional(),
  provenance: z.enum(["exact", "inferred", "legacy"]).optional(),
  route: z.string().nullable().optional(),
});

export const messageArtifactRefSchema = z.object({
  ref: z.string(),
  kind: z.string(),
  content_hash: z.string(),
  source_turn_id: z.string().nullable().optional(),
  role: z.string().optional(),
  title: z.string().nullable().optional(),
  route: z.string().nullable().optional(),
});

export const messageContextManifestSchema = z.object({
  schema: z.literal("workspace.message-context/v1"),
  message_id: z.string(),
  run_id: z.string(),
  source_turn_id: z.string(),
  considered_context: z.array(z.record(z.string(), z.unknown())).optional(),
  cited_evidence: z.array(z.string()).optional(),
  context_refs: z.array(messageContextRefSchema).optional(),
  reference_sets: z.array(z.record(z.string(), z.unknown())).optional(),
  artifacts: z.array(messageArtifactRefSchema).optional(),
  stale_refs: z.array(z.record(z.string(), z.unknown())).optional(),
  provenance: z.enum(["exact", "inferred", "legacy"]).default("exact"),
});

export const agentRunSchema = z.object({
  id: z.string(),
  assistant_message_id: z.string().optional(),
  thread_id: z.string(),
  status: agentRunStatusSchema,
  scope: z.string(),
  chat_id: z.string().nullable().optional(),
  post_id: z.string().nullable().optional(),
  post_chat_id: z.string().nullable().optional(),
  current_interrupt: z.record(z.string(), z.unknown()).nullable().optional(),
  snapshot: z.record(z.string(), z.unknown()).optional(),
  error: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable().optional(),
});

export type AgentRun = z.infer<typeof agentRunSchema>;
export type AgentSsePayload = z.infer<typeof agentSsePayloadSchema>;
export type AgentProposal = z.infer<typeof agentProposalSchema>;
export type AgentMediaJob = z.infer<typeof agentMediaJobSchema>;
export type PlannerStep = z.infer<typeof plannerStepSchema>;
export type MessageContextRef = z.infer<typeof messageContextRefSchema>;
export type MessageArtifactRef = z.infer<typeof messageArtifactRefSchema>;
export type MessageContextManifest = z.infer<typeof messageContextManifestSchema>;
