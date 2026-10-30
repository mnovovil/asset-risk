export interface TooltipRow {
  key: string;
  label: string;
  value: string;
  color: string;
}

/** Values lead and names follow, because the reader already has the series and wants the number. */
export function ChartTooltip({ title, rows }: { title: string; rows: TooltipRow[] }) {
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-title">{title}</p>
      {rows.map((row) => (
        <div className="chart-tooltip-row" key={row.key}>
          <span className="line-key" style={{ background: row.color }} />
          <strong>{row.value}</strong>
          <span>{row.label}</span>
        </div>
      ))}
    </div>
  );
}
