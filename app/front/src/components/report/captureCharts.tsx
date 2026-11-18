/**
 * The dashboard's own charts, drawn off screen in the light theme and taken apart for the PDF:
 * heading, notes, SVG and legend. Drawing the same components keeps the report and the page alike.
 */

import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";

import type { TrajectoryPoint } from "@/api/client";
import { LossBars } from "@/components/dashboard/LossBars";
import { Trajectory } from "@/components/dashboard/Trajectory";
import type { AssetRow } from "@/lib/dashboard";

/** CSS pixels: the PDF scales the vectors to the page. */
export const CHART_WIDTH_PX = 680;
const SETTLE_MS = 3_000;

export interface CapturedLegendItem {
  label: string;
  color: string;
  kind: "bar" | "line" | "diamond";
}

export interface CapturedChart {
  heading: string;
  notes: string[];
  /** null when the section has nothing to draw, e.g. scenarios with no hazard in common. */
  svg: SVGSVGElement | null;
  legend: CapturedLegendItem[];
}

export interface ChartInput {
  rows: AssetRow[];
  missing: string[];
  baseline: boolean;
  trajectory: TrajectoryPoint[];
  sharedHazards: string[];
}

const VAR = /var\((--[\w-]+)\)/g;
const COLOUR_ATTRIBUTES = ["fill", "stroke", "stop-color", "color", "style"];

/**
 * Replace each `var(--token)` in an SVG's colour attributes with its value. svg2pdf can't resolve
 * CSS variables, and every chart colour is one. Works on the element in place.
 */
export function resolveCssVars(svg: Element, lookup: (name: string) => string): void {
  for (const element of [svg, ...svg.querySelectorAll("*")]) {
    for (const name of COLOUR_ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (value?.includes("var(")) {
        element.setAttribute(name, value.replace(VAR, (_, token: string) => lookup(token) || "none"));
      }
    }
  }
}

/** "rgb(r, g, b)" from getComputedStyle as "#rrggbb", which jsPDF reads. Others pass through. */
export function hexColor(css: string): string {
  const match = css.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
  if (!match) return css;
  return `#${match
    .slice(1, 4)
    .map((n) => Number(n).toString(16).padStart(2, "0"))
    .join("")}`;
}

const nextFrame = () => new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)));

/** Every chart frame has drawn its SVG at a real size, or the time is up. */
async function settled(container: HTMLElement): Promise<void> {
  const start = performance.now();
  while (performance.now() - start < SETTLE_MS) {
    const frames = [...container.querySelectorAll(".chart-frame")];
    const drawn = frames.every((frame) => {
      const svg = frame.querySelector("svg.recharts-surface");
      return svg && Number(svg.getAttribute("width")) > 0;
    });
    if (drawn) return;
    await nextFrame();
  }
  throw new Error("The charts didn't draw.");
}

function legendKind(span: Element | null): CapturedLegendItem["kind"] {
  const kind = [...(span?.classList ?? [])].find((c) => c.startsWith("legend-"));
  return (kind?.replace("legend-", "") as CapturedLegendItem["kind"]) ?? "bar";
}

function takeApart(section: Element, lookup: (name: string) => string): CapturedChart {
  const surface = section.querySelector(".chart-frame svg.recharts-surface");
  let svg: SVGSVGElement | null = null;
  if (surface) {
    svg = surface.cloneNode(true) as SVGSVGElement;
    resolveCssVars(svg, lookup);
    svg.setAttribute("font-family", "NotoSans");
  }
  return {
    heading: section.querySelector("h2")?.textContent?.trim() ?? "",
    notes: [...section.querySelectorAll(":scope > .panel-note")]
      .map((p) => p.textContent?.replace(/\s+/g, " ").trim() ?? "")
      .filter(Boolean),
    svg,
    legend: [...section.querySelectorAll(".chart-legend li")].map((li) => {
      const span = li.querySelector("span");
      return {
        label: li.textContent?.trim() ?? "",
        // Computed, so a var() comes back as a real colour.
        color: span ? hexColor(getComputedStyle(span).backgroundColor) : "#000000",
        kind: legendKind(span),
      };
    }),
  };
}

/** Annual loss by hazard, then change over time, as the dashboard draws them. */
export async function captureCharts(input: ChartInput): Promise<CapturedChart[]> {
  const container = document.createElement("div");
  container.className = "report-offscreen theme-light";
  container.style.width = `${CHART_WIDTH_PX}px`;
  container.setAttribute("aria-hidden", "true");
  document.body.append(container);
  const root = createRoot(container);
  try {
    flushSync(() =>
      root.render(
        <>
          <LossBars
            rows={input.rows}
            missing={input.missing}
            baseline={input.baseline}
            onSelect={() => undefined}
          />
          <Trajectory trajectory={input.trajectory} sharedHazards={input.sharedHazards} />
        </>,
      ),
    );
    await settled(container);
    const tokens = getComputedStyle(container);
    const lookup = (name: string) => tokens.getPropertyValue(name).trim();
    return [...container.querySelectorAll(":scope > section")].map((s) => takeApart(s, lookup));
  } finally {
    root.unmount();
    container.remove();
  }
}
