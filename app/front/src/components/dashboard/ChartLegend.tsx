export interface LegendItem {
  key: string;
  label: string;
  color: string;
  kind: "bar" | "line" | "diamond";
}

/** Names wear text colours, and the mark beside each one carries its identity. */
export function ChartLegend({ items }: { items: LegendItem[] }) {
  return (
    <ul className="chart-legend">
      {items.map((item) => (
        <li key={item.key}>
          <span className={`legend-${item.kind}`} style={{ background: item.color }} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
