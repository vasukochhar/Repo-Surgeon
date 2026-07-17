import type { UpgradeCategory, UpgradePlan } from "@/lib/types";

const CATEGORY_STYLES: Record<UpgradeCategory, string> = {
  security: "bg-red-600/20 text-red-300",
  major: "bg-orange-600/20 text-orange-300",
  minor: "bg-blue-600/20 text-blue-300",
  patch: "bg-neutral-700 text-neutral-300",
};

export function PlanTable({ plan }: { plan: UpgradePlan }) {
  if (plan.items.length === 0) return null;
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
      <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-neutral-500">Upgrade plan</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-neutral-500">
              <th className="pb-2 pr-4 font-medium">Dependency</th>
              <th className="pb-2 pr-4 font-medium">Change</th>
              <th className="pb-2 pr-4 font-medium">Category</th>
              <th className="pb-2 pr-4 font-medium">Risk</th>
              <th className="pb-2 font-medium">Rationale</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800">
            {plan.items.map((item) => (
              <tr key={item.id}>
                <td className="py-2 pr-4 font-mono text-xs text-neutral-200">{item.dependency}</td>
                <td className="py-2 pr-4 font-mono text-xs text-neutral-400">
                  {item.from_version} → {item.to_version}
                </td>
                <td className="py-2 pr-4">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${CATEGORY_STYLES[item.category]}`}>
                    {item.category}
                  </span>
                </td>
                <td className="py-2 pr-4">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-neutral-800">
                      <div className="h-full bg-blue-500" style={{ width: `${Math.round(item.risk * 100)}%` }} />
                    </div>
                    <span className="text-xs text-neutral-500">{Math.round(item.risk * 100)}%</span>
                  </div>
                </td>
                <td className="max-w-xs truncate py-2 text-xs text-neutral-400" title={item.rationale}>
                  {item.rationale}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
