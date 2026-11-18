/**
 * Build the PDF report in the browser: the map from an off-screen MapLibre map at print resolution,
 * the charts as vectors from the dashboard's own SVGs, and text as text.
 *
 * Loaded on demand (jsPDF, svg2pdf.js and the fonts only download when someone asks for a report).
 */

import { jsPDF } from "jspdf";
import { svg2pdf } from "svg2pdf.js";

import boldFontUrl from "@/assets/fonts/NotoSans-Bold.ttf?url";
import regularFontUrl from "@/assets/fonts/NotoSans-Regular.ttf?url";
import { snapshotMap, SnapshotError } from "@/components/mapSnapshot";
import { type CapturedChart, captureCharts, CHART_WIDTH_PX } from "@/components/report/captureCharts";
import { NO_RESULT_COLOR } from "@/lib/mapColors";
import { pointRing } from "@/lib/mapStyle";
import { pageFormat, type ReportContent, reportContent, reportFileName, type ReportInput } from "@/lib/report";
import type { LegendItem } from "@/lib/mapLegend";
import { mapViewFeatures } from "@/lib/thumbnail";
import { isBaseline } from "@/lib/dashboard";

export type ReportStage = "map" | "charts" | "pdf";

export interface ReportRequest {
  input: ReportInput;
  /** Hazards the selected scenario has no data for, as the loss chart names them. */
  missing: string[];
  locale?: string;
  onStage?: (stage: ReportStage) => void;
  cancelled?: () => boolean;
}

export interface Report {
  blob: Blob;
  fileName: string;
}

/** A failure a reader can act on. Its message completes "Couldn't build the report: …". */
export class ReportError extends Error {
  name = "ReportError";
}

// Layout, in millimetres. The content box fits both A4 and US Letter.
const CONTENT_WIDTH = 180;
const TOP = 16;
const FOOTER_GAP = 14;
const GAP = 6;
// The map's CSS size at print resolution: 2040 × 1359 px for a 180 × 120 mm slot, about 290 dpi.
const MAP_WIDTH_PX = 680;
const MAP_HEIGHT_PX = 453;
const MAP_PIXEL_RATIO = 3;
const MAP_HEIGHT = (CONTENT_WIDTH * MAP_HEIGHT_PX) / MAP_WIDTH_PX;
const FONT = "NotoSans";
const PT = 0.3528; // mm per point

interface Theme {
  ink: string;
  muted: string;
  line: string;
  card: string;
}

/** The light theme's tokens from styles.css, so the PDF uses no colour of its own. */
function lightTheme(): Theme {
  const probe = document.createElement("div");
  probe.className = "theme-light report-offscreen";
  document.body.append(probe);
  const style = getComputedStyle(probe);
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  const theme = {
    ink: read("--ink", "#0b0b0b"),
    muted: read("--muted", "#52514e"),
    line: read("--line", "#e6e5e0"),
    card: read("--card", "#ffffff"),
  };
  probe.remove();
  return theme;
}

async function fontBase64(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) throw new ReportError("its font didn't load. Try again.");
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

async function addFonts(doc: jsPDF): Promise<void> {
  const [regular, bold] = await Promise.all([fontBase64(regularFontUrl), fontBase64(boldFontUrl)]);
  doc.addFileToVFS("NotoSans-Regular.ttf", regular);
  doc.addFont("NotoSans-Regular.ttf", FONT, "normal");
  doc.addFileToVFS("NotoSans-Bold.ttf", bold);
  doc.addFont("NotoSans-Bold.ttf", FONT, "bold");
  doc.setFont(FONT, "normal");
}

/** Draws top to bottom, starting a new page when the next block wouldn't fit. */
class Layout {
  y = TOP;
  readonly left: number;
  readonly bottom: number;

  constructor(
    readonly doc: jsPDF,
    readonly theme: Theme,
  ) {
    this.left = (doc.internal.pageSize.getWidth() - CONTENT_WIDTH) / 2;
    this.bottom = doc.internal.pageSize.getHeight() - FOOTER_GAP;
  }

  fits(height: number) {
    return this.y + height <= this.bottom;
  }

  ensure(height: number) {
    if (!this.fits(height) && this.y > TOP) this.newPage();
  }

  newPage() {
    this.doc.addPage();
    this.y = TOP;
  }

  /** Wrapped text; returns its height. */
  text(
    content: string,
    { size = 9, bold = false, color = this.theme.ink, width = CONTENT_WIDTH, x = this.left } = {},
  ): number {
    const { doc } = this;
    doc.setFont(FONT, bold ? "bold" : "normal");
    doc.setFontSize(size);
    doc.setTextColor(color);
    const lines = doc.splitTextToSize(content, width) as string[];
    const lineHeight = size * PT * 1.35;
    this.ensure(lines.length * lineHeight);
    doc.text(lines, x, this.y, { baseline: "top", lineHeightFactor: 1.35 });
    const height = lines.length * lineHeight;
    this.y += height;
    return height;
  }

  heading(content: string) {
    this.ensure(12);
    this.text(content, { size: 12, bold: true });
    this.y += 1.5;
  }
}

function drawHeader(layout: Layout, content: ReportContent) {
  const { doc, theme } = layout;
  layout.text(content.title, { size: 17, bold: true });
  layout.y += 3;

  const columnWidth = CONTENT_WIDTH / content.facts.length;
  const top = layout.y;
  let height = 0;
  content.facts.forEach((fact, i) => {
    layout.y = top;
    const x = layout.left + i * columnWidth;
    const h =
      layout.text(fact.label, { size: 7.5, color: theme.muted, x, width: columnWidth - 3 }) +
      layout.text(fact.value, { size: 9.5, bold: true, x, width: columnWidth - 3 });
    height = Math.max(height, h);
  });
  layout.y = top + height + GAP;

  // The headline figures, as the dashboard's tiles.
  const kpiWidth = CONTENT_WIDTH / content.kpis.length;
  const kpiTop = layout.y;
  let kpiHeight = 0;
  content.kpis.forEach((kpi, i) => {
    layout.y = kpiTop + 3;
    const x = layout.left + i * kpiWidth + 3;
    const width = kpiWidth - 6;
    layout.text(kpi.label, { size: 7.5, color: theme.muted, x, width });
    layout.y += 0.5;
    layout.text(kpi.value, { size: 14, bold: true, x, width });
    if (kpi.note) layout.text(kpi.note, { size: 7, color: theme.muted, x, width });
    kpiHeight = Math.max(kpiHeight, layout.y - kpiTop + 3);
  });
  doc.setDrawColor(theme.line);
  doc.setLineWidth(0.3);
  content.kpis.forEach((_, i) => {
    doc.roundedRect(layout.left + i * kpiWidth + 0.5, kpiTop, kpiWidth - 1, kpiHeight, 1.5, 1.5, "S");
  });
  layout.y = kpiTop + kpiHeight + 3;
  layout.text(content.typeSource, { size: 8, color: theme.muted });
  layout.y += GAP;
}

function drawMapLegend(layout: Layout, items: LegendItem[]) {
  const { doc, theme } = layout;
  const size = 7.5;
  doc.setFontSize(size);
  let x = layout.left;
  const lineHeight = 4.6;
  layout.ensure(lineHeight);
  const right = layout.left + CONTENT_WIDTH;
  for (const item of items) {
    const marker = item.kind === "heading" || item.kind === "text" ? 0 : item.kind === "bubble" ? 4.6 : 3.4;
    doc.setFont(FONT, "normal");
    const labelWidth = doc.getTextWidth(item.label);
    const width = marker + (marker ? 1.2 : 0) + labelWidth + 4;
    if (x + width > right && x > layout.left) {
      x = layout.left;
      layout.y += lineHeight;
      layout.ensure(lineHeight);
    }
    const cy = layout.y + lineHeight / 2 - 0.4;
    if (item.kind === "dot") {
      doc.setFillColor(item.color);
      doc.circle(x + marker / 2, cy, marker / 2, "F");
    } else if (item.kind === "hollow" || item.kind === "bubble") {
      doc.setDrawColor(NO_RESULT_COLOR);
      doc.setLineWidth(0.5);
      doc.circle(x + marker / 2, cy, marker / 2 - 0.25, "S");
    }
    doc.setTextColor(item.kind === "heading" ? theme.ink : theme.muted);
    doc.text(item.label, x + marker + (marker ? 1.2 : 0), cy, { baseline: "middle" });
    if (labelWidth + marker > CONTENT_WIDTH) {
      // Too long for one line: wrap it on its own.
      layout.y += lineHeight;
      x = layout.left;
    } else {
      x += width;
    }
  }
  layout.y += lineHeight + GAP;
}

async function drawMap(
  layout: Layout,
  content: ReportContent,
  input: ReportInput,
  cancelled: () => boolean,
) {
  const { doc, theme } = layout;
  layout.heading(content.map.heading);
  layout.text(content.map.caption, { size: 8.5, color: theme.muted });
  layout.y += 2;

  const view = mapViewFeatures(
    input.run.assets,
    input.run.clusters,
    input.rows,
    input.colorBy,
    false,
    pointRing(false),
  );
  if (!view.bounds) {
    layout.text("No asset could be placed on the map.", { size: 9, color: theme.muted });
    layout.y += GAP;
    return;
  }

  let snapshot;
  try {
    snapshot = await snapshotMap(view, {
      width: MAP_WIDTH_PX,
      height: MAP_HEIGHT_PX,
      pixelRatio: MAP_PIXEL_RATIO,
      dark: false,
      onBasemapError: "fail",
      cancelled,
    });
  } catch (error) {
    if (error instanceof SnapshotError) {
      const reasons: Record<SnapshotError["reason"], string> = {
        tiles: "the map tiles didn't load. Check the connection and try again.",
        timeout: "the map tiles took too long to load. Try again.",
        no_webgl: "this browser can't draw the map.",
        cancelled: "it was cancelled.",
      };
      throw new ReportError(reasons[error.reason]);
    }
    throw error;
  }

  layout.ensure(MAP_HEIGHT);
  const top = layout.y;
  doc.addImage(snapshot.src, "PNG", layout.left, top, CONTENT_WIDTH, MAP_HEIGHT, undefined, "NONE");
  doc.setDrawColor(theme.line);
  doc.setLineWidth(0.3);
  doc.rect(layout.left, top, CONTENT_WIDTH, MAP_HEIGHT, "S");

  // The basemap's credits stay on the picture, as MapLibre shows them.
  if (snapshot.attribution) {
    doc.setFont(FONT, "normal");
    doc.setFontSize(6);
    const width = Math.min(doc.getTextWidth(snapshot.attribution) + 3, CONTENT_WIDTH);
    const height = 4;
    doc.setFillColor(theme.card);
    doc.rect(layout.left + CONTENT_WIDTH - width, top + MAP_HEIGHT - height, width, height, "F");
    doc.setTextColor(theme.muted);
    doc.text(snapshot.attribution, layout.left + CONTENT_WIDTH - 1.5, top + MAP_HEIGHT - height / 2, {
      align: "right",
      baseline: "middle",
      maxWidth: CONTENT_WIDTH - 3,
    });
  }
  layout.y = top + MAP_HEIGHT + 3;
  drawMapLegend(layout, content.map.legend);
}

function chartLegend(layout: Layout, chart: CapturedChart) {
  const { doc, theme } = layout;
  doc.setFont(FONT, "normal");
  doc.setFontSize(7.5);
  const lineHeight = 4.6;
  const right = layout.left + CONTENT_WIDTH;
  let x = layout.left;
  layout.ensure(lineHeight);
  for (const item of chart.legend) {
    const width = 4.5 + doc.getTextWidth(item.label) + 5;
    if (x + width > right && x > layout.left) {
      x = layout.left;
      layout.y += lineHeight;
      layout.ensure(lineHeight);
    }
    const cy = layout.y + lineHeight / 2 - 0.4;
    doc.setFillColor(item.color);
    if (item.kind === "line") doc.rect(x, cy - 0.5, 3.5, 1, "F");
    else if (item.kind === "diamond") {
      doc.triangle(x + 1.75, cy - 1.75, x + 3.5, cy, x, cy, "F");
      doc.triangle(x, cy, x + 3.5, cy, x + 1.75, cy + 1.75, "F");
    } else doc.rect(x, cy - 1.6, 3.2, 3.2, "F");
    doc.setTextColor(theme.muted);
    doc.text(item.label, x + 4.5, cy, { baseline: "middle" });
    x += width;
  }
  layout.y += lineHeight + GAP;
}

async function drawChart(layout: Layout, chart: CapturedChart) {
  const { svg } = chart;
  const svgHeight = svg
    ? (CONTENT_WIDTH * Number(svg.getAttribute("height"))) / Number(svg.getAttribute("width"))
    : 0;
  // Keep the heading with its chart.
  layout.ensure(14 + Math.min(svgHeight, 120));
  layout.heading(chart.heading);
  const [first, ...rest] = chart.notes;
  if (first) layout.text(first, { size: 8.5, color: layout.theme.muted });
  layout.y += 2;
  if (svg) {
    layout.ensure(svgHeight);
    // svg2pdf reads layout from the document, so the copy is attached while it draws.
    const holder = document.createElement("div");
    holder.className = "report-offscreen theme-light";
    holder.style.width = `${CHART_WIDTH_PX}px`;
    holder.append(svg);
    document.body.append(holder);
    try {
      await svg2pdf(svg, layout.doc, {
        x: layout.left,
        y: layout.y,
        width: CONTENT_WIDTH,
        height: svgHeight,
      });
    } finally {
      holder.remove();
    }
    layout.y += svgHeight + 2;
    chartLegend(layout, chart);
  }
  for (const note of rest) {
    layout.text(note, { size: 8, color: layout.theme.muted });
    layout.y += 1;
  }
  layout.y += GAP;
}

function drawNotes(layout: Layout, content: ReportContent) {
  layout.heading("Reading this report");
  for (const group of content.notes) {
    layout.ensure(12);
    layout.text(group.heading, { size: 9.5, bold: true });
    layout.y += 1;
    for (const sentence of group.sentences) {
      layout.text(`•  ${sentence}`, { size: 8.5, x: layout.left + 2, width: CONTENT_WIDTH - 2 });
      layout.y += 0.6;
    }
    layout.y += 3;
  }
  layout.text(content.sourceNote, { size: 8, color: layout.theme.muted });
}

function drawFooters(layout: Layout, content: ReportContent) {
  const { doc, theme } = layout;
  const pages = doc.getNumberOfPages();
  const y = doc.internal.pageSize.getHeight() - 9;
  for (let page = 1; page <= pages; page++) {
    doc.setPage(page);
    doc.setFont(FONT, "normal");
    doc.setFontSize(7);
    doc.setTextColor(theme.muted);
    doc.text(content.footer, layout.left, y, { maxWidth: CONTENT_WIDTH - 25 });
    doc.text(`Page ${page} of ${pages}`, layout.left + CONTENT_WIDTH, y, { align: "right" });
  }
}

export async function buildReport(request: ReportRequest): Promise<Report> {
  const { input, onStage } = request;
  const cancelled = request.cancelled ?? (() => false);
  const checkCancelled = () => {
    if (cancelled()) throw new ReportError("it was cancelled.");
  };
  const content = reportContent(input);
  const theme = lightTheme();
  const doc = new jsPDF({
    unit: "mm",
    format: pageFormat(request.locale),
    orientation: "portrait",
    compress: true,
  });
  doc.setProperties({ title: `${content.title} · asset-risk report`, creator: "asset-risk" });
  await addFonts(doc);
  const layout = new Layout(doc, theme);

  onStage?.("map");
  drawHeader(layout, content);
  await drawMap(layout, content, input, cancelled);
  checkCancelled();

  onStage?.("charts");
  if (content.noResults) {
    layout.text(content.noResults, { size: 10 });
  } else {
    const charts = await captureCharts({
      rows: input.rows,
      missing: request.missing,
      baseline: isBaseline(input.pair),
      trajectory: input.run.trajectory,
      sharedHazards: input.run.summary.shared_hazards,
    });
    checkCancelled();
    onStage?.("pdf");
    layout.newPage();
    for (const chart of charts) await drawChart(layout, chart);
  }

  onStage?.("pdf");
  layout.newPage();
  drawNotes(layout, content);
  drawFooters(layout, content);
  checkCancelled();
  return { blob: doc.output("blob"), fileName: reportFileName(input.label, input.pair) };
}
