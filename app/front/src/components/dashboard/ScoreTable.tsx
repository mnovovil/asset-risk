import { useMemo, useState } from "react";

import {
  byTotalDescending,
  hazardColumns,
  SCORE_NOTES,
  scoreKind,
  type AssetRow,
} from "@/lib/dashboard";
import { joinList, percent } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";

const PAGE_SIZE = 25;
const ASSET_COLUMN = "asset";
const TOTAL_COLUMN = "total";

interface Sort {
  column: string;
  ascending: boolean;
}

function compare(a: AssetRow, b: AssetRow, { column, ascending }: Sort): number {
  let result: number;
  if (column === ASSET_COLUMN) {
    result = a.label.localeCompare(b.label);
  } else if (column === TOTAL_COLUMN) {
    result = (a.total ?? -1) - (b.total ?? -1);
  } else {
    // Rows with no result stay at the bottom whichever way a column is sorted.
    const sa = a.scores[column]?.score ?? -1;
    const sb = b.scores[column]?.score ?? -1;
    if ((sa < 0) !== (sb < 0)) return sa < 0 ? 1 : -1;
    result = sa - sb || (a.aal[column] ?? 0) - (b.aal[column] ?? 0);
  }
  return (ascending ? result : -result) || byTotalDescending(a, b);
}

function ScoreCell({ row, hazard }: { row: AssetRow; hazard: string }) {
  const score = row.scores[hazard];
  const aal = row.aal[hazard];
  if (!score) return <td className="score-cell score-none">Not returned</td>;
  const kind = scoreKind(score.score);
  if (kind !== "scored") {
    return (
      <td className="score-cell score-none">
        {kind === "no_data" && aal !== undefined ? percent(aal) : SCORE_NOTES[kind]}
      </td>
    );
  }
  return (
    <td className="score-cell">
      <span className="score-value">{percent(aal)}</span>
      <span className="score-label">{score.label}</span>
    </td>
  );
}

interface ScoreTableProps {
  rows: AssetRow[];
  onSelect: (rowNum: number) => void;
}

export function ScoreTable({ rows, onSelect }: ScoreTableProps) {
  const [sort, setSort] = useState<Sort>({ column: TOTAL_COLUMN, ascending: false });
  const [page, setPage] = useState(0);
  const columns = useMemo(() => hazardColumns(rows), [rows]);
  const sorted = useMemo(() => [...rows].sort((a, b) => compare(a, b, sort)), [rows, sort]);

  const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const visible = sorted.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  function sortBy(column: string) {
    setPage(0);
    setSort((previous) =>
      previous.column === column
        ? { column, ascending: !previous.ascending }
        : { column, ascending: column === ASSET_COLUMN },
    );
  }

  const header = (column: string, label: string) => (
    <th
      key={column}
      scope="col"
      aria-sort={
        sort.column === column ? (sort.ascending ? "ascending" : "descending") : "none"
      }
    >
      <button type="button" className="sort-button" onClick={() => sortBy(column)}>
        {label}
        {sort.column === column && (sort.ascending ? " ↑" : " ↓")}
      </button>
    </th>
  );

  return (
    <section className="panel" aria-labelledby="scores-heading">
      <h2 id="scores-heading">Risk by asset and hazard</h2>
      <p className="panel-note">
        Annual loss and physrisk's score for each hazard. "No model" and "No data" mean there's no
        result, which isn't the same as low risk.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {header(ASSET_COLUMN, "Asset")}
              {header(TOTAL_COLUMN, "Total")}
              {columns.scored.map((hazard) => header(hazard, hazardLabel(hazard)))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.rowNum}>
                <th scope="row">
                  <button type="button" className="link-button" onClick={() => onSelect(row.rowNum)}>
                    {row.label}
                  </button>
                </th>
                <td className="total-cell">{percent(row.total)}</td>
                {columns.scored.map((hazard) => (
                  <ScoreCell key={hazard} row={row} hazard={hazard} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="pagination">
          <button
            type="button"
            className="button"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            Previous
          </button>
          <span>
            Page {current + 1} of {pages}
          </span>
          <button
            type="button"
            className="button"
            disabled={current === pages - 1}
            onClick={() => setPage(current + 1)}
          >
            Next
          </button>
        </div>
      )}
      {columns.noModel.length > 0 && (
        <p className="panel-note">
          No damage model for this building type: {joinList(columns.noModel.map(hazardLabel))}.
        </p>
      )}
      {columns.noData.length > 0 && (
        <p className="panel-note">
          No hazard data at these locations: {joinList(columns.noData.map(hazardLabel))}.
        </p>
      )}
    </section>
  );
}
