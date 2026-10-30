import { REQUIRED_COLUMNS, type CsvInspection } from "@/lib/csv";

export function CsvPreview({ preview, rowCount }: Pick<CsvInspection, "preview" | "rowCount">) {
  return (
    <div className="table-scroll">
      <table>
        <caption>
          {preview.length < rowCount
            ? `First ${preview.length} of ${rowCount.toLocaleString()} rows`
            : `${rowCount.toLocaleString()} ${rowCount === 1 ? "row" : "rows"}`}
        </caption>
        <thead>
          <tr>
            {REQUIRED_COLUMNS.map((name) => (
              <th key={name} scope="col">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.map((row, index) => (
            <tr key={index}>
              {row.map((cell, column) => (
                <td key={column}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
