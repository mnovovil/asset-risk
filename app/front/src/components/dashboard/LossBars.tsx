import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { barData, TOP_ASSETS, type AssetRow } from "@/lib/dashboard";
import { joinList, percent, percentTick, truncate } from "@/lib/format";
import { hazardColor, hazardLabel, sortHazards } from "@/lib/hazards";

import { ChartLegend } from "./ChartLegend";
import { ChartTooltip } from "./ChartTooltip";

const ROW_HEIGHT = 34;
const CHART_CHROME = 44;
const BAR_THICKNESS = 18;
const LABEL_LENGTH = 18;
const END_RADIUS = 4;

type Datum = ReturnType<typeof barData>[number];

interface SegmentProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  fill?: string;
  hazard: string;
  payload?: Datum;
}

/** A stack segment. The surface-coloured stroke is the gap, and only a stack's end is rounded. */
function Segment({ x = 0, y = 0, width = 0, height = 0, fill, hazard, payload }: SegmentProps) {
  if (width <= 0) return null;
  const radius = payload?.lastHazard === hazard ? Math.min(END_RADIUS, width) : 0;
  const path = `M${x},${y}H${x + width - radius}Q${x + width},${y} ${x + width},${y + radius}V${
    y + height - radius
  }Q${x + width},${y + height} ${x + width - radius},${y + height}H${x}Z`;
  return <path d={path} fill={fill} stroke="var(--card)" strokeWidth={2} cursor="pointer" />;
}

const DIAMOND_RADIUS = 6;

interface DiamondProps {
  cx?: number;
  cy?: number;
  index?: number;
  value?: unknown;
}

/** The historical marker, ringed in the surface colour so it stays legible over a bar. */
function Diamond({ cx, cy, index, value }: DiamondProps) {
  if (cx === undefined || cy === undefined || value === null) return <g key={index} />;
  const r = DIAMOND_RADIUS;
  return (
    <path
      key={index}
      d={`M${cx},${cy - r}L${cx + r},${cy}L${cx},${cy + r}L${cx - r},${cy}Z`}
      fill="var(--ink)"
      stroke="var(--card)"
      strokeWidth={2}
    />
  );
}

interface LossBarsProps {
  rows: AssetRow[];
  missing: string[];
  onSelect: (rowNum: number) => void;
}

export function LossBars({ rows, missing, onSelect }: LossBarsProps) {
  const data = barData(rows);
  const hazards = sortHazards(rows.flatMap((row) => Object.keys(row.aal)));

  return (
    <section className="panel" aria-labelledby="loss-heading">
      <h2 id="loss-heading">Annual loss by hazard</h2>
      <p className="panel-note">
        Share of asset value lost per year on average.
        {rows.length > TOP_ASSETS && ` The ${TOP_ASSETS} highest of ${rows.length}.`} Diamonds show
        the historical loss over the same hazards.
        {missing.length > 0 &&
          ` ${joinList(missing.map(hazardLabel))} ${
            missing.length === 1 ? "has" : "have"
          } no data for this scenario, so ${missing.length === 1 ? "it isn't" : "they aren't"} included.`}
      </p>
      <div
        className="chart-frame"
        role="img"
        aria-label="Stacked bars of annual loss by hazard for the highest-loss assets. The table below has the same values."
      >
        <ResponsiveContainer width="100%" height={data.length * ROW_HEIGHT + CHART_CHROME}>
          <ComposedChart
            layout="vertical"
            data={data}
            margin={{ top: 4, right: 64, bottom: 4, left: 0 }}
            onClick={(state) => {
              const index = Number(state?.activeTooltipIndex);
              if (Number.isInteger(index) && data[index]) onSelect(data[index].rowNum);
            }}
          >
            <CartesianGrid horizontal={false} stroke="var(--grid)" />
            <XAxis
              type="number"
              domain={[0, "auto"]}
              tickFormatter={percentTick}
              stroke="var(--axis)"
              tick={{ fill: "var(--muted)", fontSize: 12 }}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={132}
              interval={0}
              tickFormatter={(label: string) => truncate(label, LABEL_LENGTH)}
              stroke="var(--axis)"
              tick={{ fill: "var(--ink)", fontSize: 12 }}
            />
            <Tooltip
              cursor={{ fill: "var(--grid)", fillOpacity: 0.4 }}
              content={({ active, payload }) => {
                const datum = payload?.[0]?.payload as Datum | undefined;
                if (!active || !datum) return null;
                return (
                  <ChartTooltip
                    title={datum.label}
                    rows={[
                      ...hazards.map((hazard) => ({
                        key: hazard,
                        label: hazardLabel(hazard),
                        value: percent(datum[hazard as keyof Datum] as number | undefined),
                        color: hazardColor(hazard),
                      })),
                      {
                        key: "total",
                        label: "Total",
                        value: percent(datum.total),
                        color: "var(--ink)",
                      },
                      {
                        key: "historical",
                        label: "Historical, same hazards",
                        value: percent(datum.historical),
                        color: "var(--muted)",
                      },
                    ]}
                  />
                );
              }}
            />
            {hazards.map((hazard) => (
              <Bar
                key={hazard}
                dataKey={hazard}
                name={hazardLabel(hazard)}
                stackId="loss"
                fill={hazardColor(hazard)}
                barSize={BAR_THICKNESS}
                isAnimationActive={false}
                shape={(props: object) => <Segment {...props} hazard={hazard} />}
              />
            ))}
            <Line
              dataKey="historical"
              stroke="none"
              isAnimationActive={false}
              activeDot={false}
              dot={(props: DiamondProps) => <Diamond {...props} />}
            />
            <Line
              dataKey="labelEnd"
              stroke="none"
              dot={false}
              activeDot={false}
              isAnimationActive={false}
            >
              <LabelList
                content={({ x, y, index }) => (
                  <text
                    x={Number(x) + 10}
                    y={Number(y)}
                    dominantBaseline="central"
                    fill="var(--ink)"
                    fontSize={12}
                  >
                    {percent(data[Number(index)]?.total)}
                  </text>
                )}
              />
            </Line>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend
        items={[
          ...hazards.map((hazard) => ({
            key: hazard,
            label: hazardLabel(hazard),
            color: hazardColor(hazard),
            kind: "bar" as const,
          })),
          {
            key: "historical",
            label: "Historical, same hazards",
            color: "var(--ink)",
            kind: "diamond" as const,
          },
        ]}
      />
    </section>
  );
}
