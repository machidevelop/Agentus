import { z } from "zod";

export const findingSummarySchema = z.object({
  id: z.string(),
  type: z.string(),
  job_id: z.string(),
  confidence: z.enum(["high", "medium", "low"]),
  verdict: z.enum(["LIKELY_VALID", "REVIEW", "INVALID"]),
  value: z.number(),
  detected: z.string(),
});

export type FindingSummary = z.infer<typeof findingSummarySchema>;
