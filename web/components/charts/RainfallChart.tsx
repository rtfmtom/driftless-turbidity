"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { RainfallSeries } from "@/lib/types";

export function RainfallChart({ series }: { series: RainfallSeries }) {
  const data = series.hours.map((h) => ({
    ts: new Date(h.ts).getTime(),
    label: new Date(h.ts).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
    }),
    rainfall_mm: h.rainfall_mm ?? 0,
  }));

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
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
            stroke="#64748b"
            fontSize={11}
            label={{
              value: "mm",
              angle: -90,
              position: "insideLeft",
              fontSize: 11,
              fill: "#64748b",
            }}
          />
          <Tooltip
            labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
            formatter={(v: number) => [v.toFixed(2) + " mm", "rainfall"]}
          />
          <Bar dataKey="rainfall_mm" fill="#0ea5e9" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
