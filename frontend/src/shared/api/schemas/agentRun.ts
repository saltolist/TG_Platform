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

export const agentSsePayloadSchema = z.object({
  agent: agentEventSchema.optional(),
  text: z.string().optional(),
  meta: z.record(z.string(), z.unknown()).optional(),
});

export const agentRunSchema = z.object({
  id: z.string(),
  thread_id: z.string(),
  status: agentRunStatusSchema,
  scope: z.string(),
  chat_id: z.string().nullable().optional(),
  post_id: z.string().nullable().optional(),
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
