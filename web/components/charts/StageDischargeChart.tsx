"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { GaugeReadingSeries } from "@/lib/types";

type Point = {
  ts: number;
  stage_ft?: number;
  discharge_cfs?: number;
};

export function StageDischargeChart({
  series,
}: {
  series: GaugeReadingSeries;
}) {
  // Pivot rows: (ts, parameter_code, value) → {ts, stage_ft, discharge_cfs}
  const byTs = new Map<number, Point>();
  for (const p of series.points) {
    if (p.value == null) continue;
    const ts = new Date(p.ts).getTime();
    const row = byTs.get(ts) ?? { ts };
    if (p.parameter_code === "00065") row.stage_ft = p.value;
    if (p.parameter_code === "00060") row.discharge_cfs = p.value;
    byTs.set(ts, row);
  }
  const data = Array.from(byTs.values()).sort((a, b) => a.ts - b.ts);

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
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
            yAxisId="stage"
            orientation="left"
            stroke="#0284c7"
            fontSize={11}
            label={{
              value: "stage (ft)",
              angle: -90,
              position: "insideLeft",
              fontSize: 11,
              fill: "#0284c7",
            }}
          />
          <YAxis
            yAxisId="q"
            orientation="right"
            stroke="#475569"
            fontSize={11}
            label={{
              value: "discharge (cfs)",
              angle: 90,
              position: "insideRight",
              fontSize: 11,
              fill: "#475569",
            }}
          />
          <Tooltip
            labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
            formatter={(v: number, name: string) => {
              if (name === "stage_ft") return [v.toFixed(2) + " ft", "stage"];
              if (name === "discharge_cfs") return [v.toFixed(0) + " cfs", "discharge"];
              return [v, name];
            }}
          />
          <Legend />
          <Line
            yAxisId="stage"
            type="monotone"
            dataKey="stage_ft"
            stroke="#0284c7"
            dot={false}
            strokeWidth={1.5}
            connectNulls
            name="stage"
          />
          <Line
            yAxisId="q"
            type="monotone"
            dataKey="discharge_cfs"
            stroke="#475569"
            dot={false}
            strokeWidth={1.5}
            connectNulls
            name="discharge"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
