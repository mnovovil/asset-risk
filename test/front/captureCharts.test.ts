import { describe, expect, it } from "vitest";

import { hexColor, resolveCssVars } from "@/components/report/captureCharts";

const LIGHT: Record<string, string> = {
  "--series-1": "#2a78d6",
  "--card": "#ffffff",
  "--ink": "#0b0b0b",
};

function svg(markup: string): SVGSVGElement {
  const doc = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg">${markup}</svg>`,
    "image/svg+xml",
  );
  return doc.documentElement as unknown as SVGSVGElement;
}

describe("resolveCssVars", () => {
  it("replaces every token in colour attributes with its value", () => {
    const element = svg(
      '<rect fill="var(--series-1)" stroke="var(--card)"/><text fill="var(--ink)" style="color: var(--ink)">x</text>',
    );
    resolveCssVars(element, (name) => LIGHT[name] ?? "");
    expect(element.querySelector("rect")?.getAttribute("fill")).toBe("#2a78d6");
    expect(element.querySelector("rect")?.getAttribute("stroke")).toBe("#ffffff");
    expect(element.querySelector("text")?.getAttribute("style")).toBe("color: #0b0b0b");
    expect(element.outerHTML).not.toContain("var(");
  });

  it("leaves no var() behind for an unknown token, and keeps other values", () => {
    const element = svg('<path fill="var(--nope)" stroke="#123456" d="M0 0"/>');
    resolveCssVars(element, () => "");
    expect(element.querySelector("path")?.getAttribute("fill")).toBe("none");
    expect(element.querySelector("path")?.getAttribute("stroke")).toBe("#123456");
    expect(element.querySelector("path")?.getAttribute("d")).toBe("M0 0");
  });
});

describe("hexColor", () => {
  it.each([
    ["rgb(42, 120, 214)", "#2a78d6"],
    ["rgba(0, 0, 0, 0.5)", "#000000"],
    ["rgb(255 255 255)", "#ffffff"],
    ["#eb6834", "#eb6834"],
  ])("%s → %s", (input, expected) => {
    expect(hexColor(input)).toBe(expected);
  });
});
