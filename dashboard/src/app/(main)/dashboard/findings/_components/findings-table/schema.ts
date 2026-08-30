import z from "zod";

const findingSchema = z.object({
  id: z.string(),
  type: z.string(),
  confidence_level: z.string(),
  health: z.string(),
  monthly_value: z.string(),
  verdict: z.string(),
});

export const findingsSchema = z.array(findingSchema);

export type FindingRow = z.infer<typeof findingSchema>;
