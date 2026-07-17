import type { UpgradeCategory, UpgradePlan } from "@/lib/types";
import { GlowCard } from "@/components/ui/GlowCard";
import { staggerDelay } from "@/lib/motion";

const CATEGORY_STYLES: Record<UpgradeCategory, string> = {
  security: "bg-[var(--danger)]/15 text-[var(--danger)]",
  major: "bg-orange-500/15 text-orange-300",
  minor: "bg-[var(--info)]/15 text-[var(--info)]",
  patch: "bg-[var(--surface-2)] text-[var(--text-muted)]",
};

function riskColor(risk: number): string {
  if (risk >= 0.7) return "var(--danger)";
  if (risk >= 0.4) return "var(--warn)";
  return "var(--accent)";
}

export function PlanTable({ plan }: { plan: UpgradePlan }) {
  if (plan.items.length === 0) return null;
  return (
    <GlowCard className="p-5">
      <h3 className="eyebrow mb-3">Upgrade plan</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-[var(--text-faint)]">
              <th className="pb-2 pr-4 font-medium">Dependency</th>
              <th className="pb-2 pr-4 font-medium">Change</th>
              <th className="pb-2 pr-4 font-medium">Category</th>
              <th className="pb-2 pr-4 font-medium">Risk</th>
              <th className="pb-2 font-medium">Rationale</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {plan.items.map((item, index) => (
              <tr
                key={item.id}
                className="rise-in transition-colors duration-[var(--dur-fast)] hover:bg-[var(--surface-2)]/50"
                style={{ animationDelay: staggerDelay(index) }}
              >
                <td className="py-2 pr-4 font-mono text-xs text-[var(--text)]">{item.dependency}</td>
                <td className="py-2 pr-4 font-mono text-xs text-[var(--text-muted)]">
                  {item.from_version} → {item.to_version}
                </td>
                <td className="py-2 pr-4">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${CATEGORY_STYLES[item.category]}`}>
                    {item.category}
                  </span>
                </td>
                <td className="py-2 pr-4">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[var(--surface-2)]">
                      <div
                        className="h-full rounded-full transition-[width] duration-[var(--dur-slow)] ease-[var(--ease-out)]"
                        style={{ width: `${Math.round(item.risk * 100)}%`, background: riskColor(item.risk) }}
                      />
                    </div>
                    <span className="text-xs text-[var(--text-faint)]">{Math.round(item.risk * 100)}%</span>
                  </div>
                </td>
                <td className="max-w-xs truncate py-2 text-xs text-[var(--text-muted)]" title={item.rationale}>
                  {item.rationale}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </GlowCard>
  );
}
