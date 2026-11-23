import type { Summary, TrajectoryPoint } from "@/api/client";
import { type AssetRow, kpiItems, type Weighting } from "@/lib/dashboard";

interface KpisProps {
  summary: Summary;
  point: TrajectoryPoint | undefined;
  rows: AssetRow[];
  /** Showing physrisk's baseline, which has nothing to compare with. */
  baseline: boolean;
  weighting?: Weighting;
}

export function Kpis({ summary, point, rows, baseline, weighting = "equal" }: KpisProps) {
  return (
    <dl className="kpis">
      {kpiItems(summary, point, rows, baseline, weighting).map((item) => (
        <div className="kpi" key={item.label}>
          <dt>{item.label}</dt>
          <dd>
            <span className="kpi-value">{item.value}</span>
            {item.note && <span className="kpi-note">{item.note}</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}
