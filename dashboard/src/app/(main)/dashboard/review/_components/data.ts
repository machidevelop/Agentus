import { AlertTriangle, Clock, Minus, TrendingDown, TrendingUp, ZapOff } from "lucide-react";
import { z } from "zod";

const reviewSchema = z.object({
  id: z.string(),
  title: z.string(),
  type: z.string(),
  label: z.string(),
  confidence: z.string(),
  verdict: z.string(),
});

export type Review = z.infer<typeof reviewSchema>;

const reviewsData: z.input<typeof reviewSchema>[] = [];

export const reviews = z.array(reviewSchema).parse(reviewsData);

export const labels = [
  { value: "queue", label: "Queue" },
  { value: "utilization", label: "Utilization" },
  { value: "allocation", label: "Allocation" },
  { value: "fragmentation", label: "Fragmentation" },
];

export const types = [
  { value: "idle_allocation", label: "Idle Allocation", icon: ZapOff },
  { value: "queue_inefficiency", label: "Queue Inefficiency", icon: Clock },
  { value: "over_allocation", label: "Over-Allocation", icon: AlertTriangle },
  { value: "fragmentation", label: "Fragmentation", icon: TrendingDown },
];

export const confidences = [
  { label: "High", value: "high", icon: TrendingUp },
  { label: "Medium", value: "medium", icon: Minus },
  { label: "Low", value: "low", icon: TrendingDown },
];
