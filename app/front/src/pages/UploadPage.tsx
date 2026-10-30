import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, createRun, getConfig, type AppConfig } from "@/api/client";
import { CsvPreview } from "@/components/CsvPreview";
import { DropZone } from "@/components/DropZone";
import { RunsList } from "@/components/RunsList";
import { inspectCsv, type CsvInspection } from "@/lib/csv";

const BYTES_PER_MB = 1024 * 1024;

export function UploadPage() {
  const navigate = useNavigate();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<CsvInspection | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    // Without the limits the browser checks less, and the server still enforces them.
    getConfig(controller.signal)
      .then(setConfig)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  async function chooseFile(chosen: File) {
    setFile(null);
    setInspection(null);
    setProblem(null);

    // Checked before reading, so a huge file can't hang the browser.
    if (config && chosen.size > config.max_upload_mb * BYTES_PER_MB) {
      setProblem(`${chosen.name} is over the ${config.max_upload_mb} MB limit.`);
      return;
    }
    const result = inspectCsv(await chosen.text());
    if (result.missing.length > 0) {
      setProblem(`${chosen.name} is missing the column${
        result.missing.length === 1 ? "" : "s"
      } ${result.missing.join(", ")}.`);
      return;
    }
    if (result.rowCount === 0) {
      setProblem(`${chosen.name} has no rows.`);
      return;
    }
    if (config && result.rowCount > config.max_portfolio_rows) {
      setProblem(
        `${chosen.name} has ${result.rowCount.toLocaleString()} rows. ` +
          `The limit is ${config.max_portfolio_rows.toLocaleString()}.`,
      );
      return;
    }
    setFile(chosen);
    setInspection(result);
  }

  async function upload() {
    if (!file) return;
    setUploading(true);
    setProblem(null);
    try {
      const run = await createRun(file);
      navigate(`/runs/${run.run_id}`);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "The upload failed.");
      setUploading(false);
    }
  }

  return (
    <div className="narrow">
      <section aria-labelledby="upload-heading">
        <h1 id="upload-heading">Assess a portfolio</h1>
        <p className="lede">
          Upload a list of sites to estimate their physical climate risk. Each point is matched to a
          building, which sets the damage model used for it.
        </p>
        <DropZone onFile={(chosen) => void chooseFile(chosen)} />
        <p className="muted">
          Need an example? <a href="/sample_portfolio.csv">Download a sample CSV</a>.
          {config &&
            ` Limits: ${config.max_portfolio_rows.toLocaleString()} rows, ${config.max_upload_mb} MB.`}
        </p>
        {problem && (
          <p className="notice notice-error" role="alert">
            {problem}
          </p>
        )}
        {file && inspection && (
          <div className="card">
            <h2>{file.name}</h2>
            <CsvPreview preview={inspection.preview} rowCount={inspection.rowCount} />
            <button
              type="button"
              className="button button-primary"
              disabled={uploading}
              onClick={() => void upload()}
            >
              {uploading ? "Uploading…" : "Assess this portfolio"}
            </button>
          </div>
        )}
      </section>
      <RunsList />
    </div>
  );
}
