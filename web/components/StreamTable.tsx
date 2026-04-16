import Link from "next/link";

import { ClarityBadge } from "@/components/ClarityBadge";
import type { Reading, Stream } from "@/lib/types";

const PARAMS: { code: string; label: string; unit: string }[] = [
  { code: "00060", label: "Discharge", unit: "cfs" },
  { code: "00065", label: "Stage", unit: "ft" },
  { code: "00010", label: "Water temp", unit: "°C" },
  { code: "63680", label: "Turbidity", unit: "FNU" },
];

function findReading(readings: Reading[], code: string): Reading | undefined {
  return readings.find((r) => r.parameter_code === code);
}

function formatValue(reading: Reading | undefined): string {
  if (!reading || reading.value === null) return "—";
  return reading.value.toLocaleString(undefined, {
    maximumFractionDigits: 2,
  });
}

function latestTs(readings: Reading[]): string {
  if (readings.length === 0) return "—";
  const newest = readings
    .map((r) => new Date(r.ts).getTime())
    .reduce((a, b) => Math.max(a, b));
  return new Date(newest).toLocaleString();
}

export function StreamTable({ streams }: { streams: Stream[] }) {
  if (streams.length === 0) {
    return (
      <div className="rounded border border-slate-200 bg-white p-6 text-slate-500">
        No watched streams yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-100 text-left text-slate-600">
          <tr>
            <th className="px-3 py-2">Stream</th>
            <th className="px-3 py-2">Clarity</th>
            <th className="px-3 py-2">Gauge</th>
            {PARAMS.map((p) => (
              <th key={p.code} className="px-3 py-2">
                {p.label}
                <span className="ml-1 text-xs font-normal text-slate-400">
                  ({p.unit})
                </span>
              </th>
            ))}
            <th className="px-3 py-2">
              Rain 24h
              <span className="ml-1 text-xs font-normal text-slate-400">
                (mm)
              </span>
            </th>
            <th className="px-3 py-2">Last updated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {streams.flatMap((stream) =>
            stream.gauges.length === 0
              ? [
                  <tr key={`${stream.id}-empty`}>
                    <td className="px-3 py-2 font-medium">{stream.name}</td>
                    <td className="px-3 py-2 text-slate-400" colSpan={PARAMS.length + 4}>
                      No linked gauges
                    </td>
                  </tr>,
                ]
              : stream.gauges.map((gauge) => (
                  <tr key={`${stream.id}-${gauge.usgs_site_id}`}>
                    <td className="px-3 py-2">
                      <div className="flex flex-col">
                        <Link
                          href={`/streams/${stream.id}`}
                          className="font-medium text-slate-900 hover:underline"
                        >
                          {stream.name}
                        </Link>
                        {stream.basin_area_km2 != null && (
                          <span className="text-xs text-slate-400">
                            basin{" "}
                            {stream.basin_area_km2.toLocaleString(undefined, {
                              maximumFractionDigits: 0,
                            })}{" "}
                            km²
                            {stream.pct_row_crop != null && (
                              <> · {stream.pct_row_crop.toFixed(0)}% row crop</>
                            )}
                          </span>
                        )}
                        {(stream.dominant_hsg != null ||
                          stream.runoff_curve_number != null) && (
                          <span className="text-xs text-slate-400">
                            {stream.dominant_hsg != null && (
                              <>HSG {stream.dominant_hsg}</>
                            )}
                            {stream.dominant_hsg != null &&
                              stream.runoff_curve_number != null && " · "}
                            {stream.runoff_curve_number != null && (
                              <>CN {stream.runoff_curve_number.toFixed(0)}</>
                            )}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <ClarityBadge
                        cls={stream.clarity_class}
                        confidence={stream.clarity_confidence}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-col">
                        <span>{gauge.name}</span>
                        <span className="text-xs text-slate-400">
                          {gauge.usgs_site_id}
                          {gauge.relationship !== "on_stream"
                            ? ` · ${gauge.relationship}`
                            : ""}
                        </span>
                      </div>
                    </td>
                    {PARAMS.map((p) => (
                      <td key={p.code} className="px-3 py-2 tabular-nums">
                        {formatValue(findReading(gauge.latest_readings, p.code))}
                      </td>
                    ))}
                    <td className="px-3 py-2 tabular-nums">
                      {stream.rainfall_24h_mm != null
                        ? stream.rainfall_24h_mm.toLocaleString(undefined, {
                            maximumFractionDigits: 1,
                          })
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {latestTs(gauge.latest_readings)}
                    </td>
                  </tr>
                ))
          )}
        </tbody>
      </table>
    </div>
  );
}
