import type { Reading, Stream } from "@/lib/types";

// 63680 (FNU) is the modern turbidity code; 63160 (TRU) is the older one
// still used at many Driftless stations (e.g. Kickapoo at La Farge and
// Steuben). Treat them as one column — the units aren't identical but
// the rough magnitudes are comparable for day-to-day clarity tracking.
const PARAMS: { codes: string[]; label: string; unit: string }[] = [
  { codes: ["00060"], label: "Discharge", unit: "cfs" },
  { codes: ["00065"], label: "Stage", unit: "ft" },
  { codes: ["00010"], label: "Water temp", unit: "°C" },
  { codes: ["63680", "63160"], label: "Turbidity", unit: "FNU/TRU" },
];

function findReading(
  readings: Reading[],
  codes: string[]
): Reading | undefined {
  for (const c of codes) {
    const r = readings.find((x) => x.parameter_code === c);
    if (r) return r;
  }
  return undefined;
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
            <th className="px-3 py-2">Gauge</th>
            {PARAMS.map((p) => (
              <th key={p.codes.join(",")} className="px-3 py-2">
                {p.label}
                <span className="ml-1 text-xs font-normal text-slate-400">
                  ({p.unit})
                </span>
              </th>
            ))}
            <th className="px-3 py-2">Last updated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {streams.flatMap((stream) =>
            stream.gauges.length === 0
              ? [
                  <tr key={`${stream.id}-empty`}>
                    <td className="px-3 py-2 font-medium">{stream.name}</td>
                    <td className="px-3 py-2 text-slate-400" colSpan={PARAMS.length + 2}>
                      No linked gauges
                    </td>
                  </tr>,
                ]
              : stream.gauges.map((gauge) => (
                  <tr key={`${stream.id}-${gauge.usgs_site_id}`}>
                    <td className="px-3 py-2 font-medium">{stream.name}</td>
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
                      <td
                        key={p.codes.join(",")}
                        className="px-3 py-2 tabular-nums"
                      >
                        {formatValue(
                          findReading(gauge.latest_readings, p.codes)
                        )}
                      </td>
                    ))}
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
