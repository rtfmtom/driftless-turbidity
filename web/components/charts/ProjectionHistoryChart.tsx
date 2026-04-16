"use client";

import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CLARITY_HEX } from "@/components/ClarityBadge";
import type { ClarityClass, ProjectionSeries } from "@/lib/types";

const ORDER: ClarityClass[] = ["clear", "tinged", "stained", "blown"];

export function ProjectionHistoryChart({ series }: { series: ProjectionSeries }) {
  const data = series.points.map((p) => ({
    ts: new Date(p.computed_at).getTime(),
    y: ORDER.indexOf(p.clarity_class) + 1,
    clarity_class: p.clarity_class,
    confidence: p.confidence,
  }));

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
          <CartesianGrid stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t) =>
              new Date(t).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              })
            }
            stroke="#64748b"
            fontSize={11}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[0.5, ORDER.length + 0.5]}
            ticks={[1, 2, 3, 4]}
            tickFormatter={(v) => ORDER[Math.round(Number(v)) - 1] ?? ""}
            stroke="#64748b"
            fontSize={11}
            width={64}
          />
          <Tooltip
            cursor={{ stroke: "#cbd5e1" }}
            labelFormatter={() => ""}
            formatter={(_v, _n, ctx: { payload?: { clarity_class?: string; confidence?: string; ts?: number } }) => {
              const p = ctx.payload ?? {};
              return [
                `${p.clarity_class ?? "—"} (${p.confidence ?? "?"})`,
                p.ts ? new Date(p.ts).toLocaleString() : "",
              ];
            }}
          />
          <Scatter
            data={data}
            fill="#94a3b8"
            shape={(props: { cx?: number; cy?: number; payload?: { clarity_class?: ClarityClass } }) => {
              const cls = (props.payload?.clarity_class ?? "clear") as ClarityClass;
              return (
                <circle
                  cx={props.cx}
                  cy={props.cy}
                  r={4}
                  fill={CLARITY_HEX[cls]}
                  stroke="#fff"
                  strokeWidth={1}
                />
              );
            }}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
