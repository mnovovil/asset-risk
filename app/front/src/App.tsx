import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { ASSET_MAP_ROUTE } from "@/lib/assetMapRoute";
import { AssetMapPage } from "@/pages/AssetMapPage";
import { PortfoliosPage } from "@/pages/PortfoliosPage";
import { RunPage } from "@/pages/RunPage";
import { UploadPage } from "@/pages/UploadPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<PortfoliosPage />} />
      <Route path="/upload" element={<UploadPage />} />
      <Route path="/runs/:runId" element={<RunPage />} />
      <Route path={ASSET_MAP_ROUTE} element={<AssetMapPage />} />
      <Route path="*" element={<p role="alert">This page doesn't exist.</p>} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <header className="site-header">
        <Link to="/" className="site-name">
          Asset Risk
        </Link>
      </header>
      <main className="site-main">
        <AppRoutes />
      </main>
    </BrowserRouter>
  );
}
