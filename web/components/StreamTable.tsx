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

type VisibleParam = { code: string; label: string; unit: string };

function BasinSubtitle({ stream }: { stream: Stream }) {
  const hasAny =
    stream.basin_area_km2 != null ||
    stream.pct_row_crop != null ||
    stream.dominant_hsg != null ||
    stream.runoff_curve_number != null;
  if (!hasAny) return null;

  return (
    <div className="text-xs text-slate-400">
      {stream.basin_area_km2 != null && (
        <>
          basin{" "}
          {stream.basin_area_km2.toLocaleString(undefined, {
            maximumFractionDigits: 0,
          })}{" "}
          km²
        </>
      )}
      {stream.pct_row_crop != null && (
        <> · {stream.pct_row_crop.toFixed(0)}% row crop</>
      )}
      {stream.dominant_hsg != null && <> · HSG {stream.dominant_hsg}</>}
      {stream.runoff_curve_number != null && (
        <> · CN {stream.runoff_curve_number.toFixed(0)}</>
      )}
    </div>
  );
}

export function StreamTable({ streams }: { streams: Stream[] }) {
  if (streams.length === 0) {
    return (
      <div className="rounded border border-slate-200 bg-white p-6 text-slate-500">
        No watched streams yet.
      </div>
    );
  }

  // Hide columns that are empty across every row in the current data set.
  // Self-healing: the moment a newly-added gauge starts reporting a
  // parameter (e.g., turbidity at Wisconsin R at Muscoda), its column
  // reappears without a code change.
  const visibleParams: VisibleParam[] = PARAMS.filter((p) =>
    streams.some((s) =>
      s.gauges.some((g) =>
        g.latest_readings.some(
          (r) => r.parameter_code === p.code && r.value != null
        )
      )
    )
  );
  const showRain24h = streams.some((s) => s.rainfall_24h_mm != null);

  // Stream + Clarity + Gauge + param cols + optional rain + Last-updated
  const colCount = 3 + visibleParams.length + (showRain24h ? 1 : 0) + 1;

  return (
    <>
      {/* Mobile: stack of cards. Keeps every datapoint visible without a
          horizontal scroll on phone widths. */}
      <div className="space-y-3 md:hidden" aria-label="Watch list">
        {streams.flatMap((stream) =>
          stream.gauges.length === 0
            ? [
                <MobileEmptyCard key={`${stream.id}-empty`} stream={stream} />,
              ]
            : stream.gauges.map((gauge) => (
                <MobileStreamCard
                  key={`${stream.id}-${gauge.usgs_site_id}`}
                  stream={stream}
                  gauge={gauge}
                  visibleParams={visibleParams}
                  showRain24h={showRain24h}
                />
              ))
        )}
      </div>

      {/* Desktop: the full table. */}
      <div className="hidden overflow-x-auto rounded border border-slate-200 bg-white md:block">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-100 text-left text-slate-600">
            <tr>
              <th className="px-3 py-2">Stream</th>
              <th className="px-3 py-2">Clarity</th>
              <th className="px-3 py-2">Gauge</th>
              {visibleParams.map((p) => (
                <th key={p.code} className="px-3 py-2">
                  {p.label}
                  <span className="ml-1 text-xs font-normal text-slate-400">
                    ({p.unit})
                  </span>
                </th>
              ))}
              {showRain24h && (
                <th className="px-3 py-2">
                  Rain 24h
                  <span className="ml-1 text-xs font-normal text-slate-400">
                    (mm)
                  </span>
                </th>
              )}
              <th className="px-3 py-2">Last updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {streams.flatMap((stream) =>
              stream.gauges.length === 0
                ? [
                    <tr key={`${stream.id}-empty`}>
                      <td className="px-3 py-2 font-medium">{stream.name}</td>
                      <td
                        className="px-3 py-2 text-slate-400"
                        colSpan={colCount - 1}
                      >
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
                          <BasinSubtitle stream={stream} />
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
                      {visibleParams.map((p) => (
                        <td
                          key={p.code}
                          className="px-3 py-2 tabular-nums"
                        >
                          {formatValue(
                            findReading(gauge.latest_readings, p.code)
                          )}
                        </td>
                      ))}
                      {showRain24h && (
                        <td className="px-3 py-2 tabular-nums">
                          {stream.rainfall_24h_mm != null
                            ? stream.rainfall_24h_mm.toLocaleString(undefined, {
                                maximumFractionDigits: 1,
                              })
                            : "—"}
                        </td>
                      )}
                      <td className="px-3 py-2 text-xs text-slate-500">
                        {latestTs(gauge.latest_readings)}
                      </td>
                    </tr>
                  ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function MobileEmptyCard({ stream }: { stream: Stream }) {
  return (
    <Link
      href={`/streams/${stream.id}`}
      className="block rounded border border-slate-200 bg-white p-4 active:bg-slate-50"
    >
      <div className="font-medium">{stream.name}</div>
      <BasinSubtitle stream={stream} />
      <div className="mt-2 text-sm text-slate-400">No linked gauges</div>
    </Link>
  );
}

function MobileStreamCard({
  stream,
  gauge,
  visibleParams,
  showRain24h,
}: {
  stream: Stream;
  gauge: Stream["gauges"][number];
  visibleParams: VisibleParam[];
  showRain24h: boolean;
}) {
  const metrics: { label: string; value: string }[] = [];
  for (const p of visibleParams) {
    metrics.push({
      label: `${p.label} (${p.unit})`,
      value: formatValue(findReading(gauge.latest_readings, p.code)),
    });
  }
  if (showRain24h) {
    metrics.push({
      label: "Rain 24h (mm)",
      value:
        stream.rainfall_24h_mm != null
          ? stream.rainfall_24h_mm.toLocaleString(undefined, {
              maximumFractionDigits: 1,
            })
          : "—",
    });
  }

  return (
    <Link
      href={`/streams/${stream.id}`}
      className="block rounded border border-slate-200 bg-white p-4 active:bg-slate-50"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium text-slate-900">
            {stream.name}
          </div>
          <BasinSubtitle stream={stream} />
        </div>
        <ClarityBadge
          cls={stream.clarity_class}
          confidence={stream.clarity_confidence}
        />
      </div>

      <div className="mt-3 text-xs text-slate-500">
        <div className="truncate">{gauge.name}</div>
        <div className="text-slate-400">
          {gauge.usgs_site_id}
          {gauge.relationship !== "on_stream"
            ? ` · ${gauge.relationship}`
            : ""}
        </div>
      </div>

      {metrics.length > 0 && (
        <dl className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4">
          {metrics.map((m) => (
            <div
              key={m.label}
              className="rounded bg-slate-50 px-2 py-1.5 text-center"
            >
              <dt className="text-[10px] uppercase tracking-wide text-slate-500">
                {m.label}
              </dt>
              <dd className="tabular-nums text-sm font-medium text-slate-900">
                {m.value}
              </dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-2 text-[11px] text-slate-400">
        Updated {latestTs(gauge.latest_readings)}
      </div>
    </Link>
  );
}
