import { z } from "zod";

export const findingRowSchema = z.object({
  id: z.string(),
  job_id: z.string(),
  cluster: z.string(),
  type: z.string(),
  confidence: z.enum(["high", "medium", "low"]),
  value: z.string(),
  status: z.string(),
  health: z.enum(["High Confidence", "Medium Confidence", "Low Confidence", "Dismissed"]),
  detected: z.string(),
});

export type FindingRow = z.infer<typeof findingRowSchema>;
export const findingsSchema = z.array(findingRowSchema);
