export function grade(score: number | null | undefined): string | null {
  if (score == null) return null;
  if (score >= 90) return "excellent";
  if (score >= 75) return "strong";
  if (score >= 60) return "moderate";
  if (score >= 40) return "weak";
  return "poor";
}

export const GRADE_STYLES: Record<string, string> = {
  excellent: "text-emerald-400",
  strong: "text-emerald-400",
  moderate: "text-amber-400",
  weak: "text-orange-400",
  poor: "text-red-400",
};
