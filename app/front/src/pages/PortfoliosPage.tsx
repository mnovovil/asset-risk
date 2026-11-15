import { Link } from "react-router-dom";

import { PortfolioCard } from "@/components/portfolios/PortfolioCard";
import { useRuns } from "@/hooks/useRuns";

export function PortfoliosPage() {
  const { runs, error, connectionLost } = useRuns();

  return (
    <section aria-labelledby="portfolios-heading" className="portfolios-page">
      <div className="page-heading">
        <h1 id="portfolios-heading">Portfolios</h1>
        <Link to="/upload" className="button button-primary">
          New portfolio
        </Link>
      </div>
      <p className="lede">
        The climate risk results of every portfolio assessed here. Each card shows the scenario and
        year the dashboard opens on, which can differ between portfolios.
      </p>

      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      {!runs && !error && <p className="muted">Loading…</p>}
      {connectionLost && (
        <p className="notice notice-warning" role="status">
          Lost contact with the server. Trying again.
        </p>
      )}
      {runs?.length === 0 && (
        <div className="empty-state">
          <p>No portfolios yet.</p>
          <p>
            <Link to="/upload">Assess a portfolio</Link> to see its results here.
          </p>
        </div>
      )}
      {runs && runs.length > 0 && (
        <ul className="portfolio-grid">
          {runs.map((run) => (
            <li key={run.run_id}>
              <PortfolioCard run={run} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
