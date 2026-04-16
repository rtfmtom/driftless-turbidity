"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";

import { ClarityBadge } from "@/components/ClarityBadge";
import { ProjectionHistoryChart } from "@/components/charts/ProjectionHistoryChart";
import { RainfallChart } from "@/components/charts/RainfallChart";
import { StageDischargeChart } from "@/components/charts/StageDischargeChart";
import { apiGet } from "@/lib/api";
import type {
  GaugeReadingSeries,
  ProjectionDetail,
  ProjectionSeries,
  RainfallSeries,
  Stream,
} from "@/lib/types";

const BasinsMap = dynamic(
  () => import("@/components/BasinsMap").then((m) => m.BasinsMap),
  { ssr: false, loading: () => <BasinPlaceholder /> }
);

const HOURS = 168; // 7 days
const REFRESH_MS = 60_000;

function BasinPlaceholder() {
  return (
    <div className="flex h-64 w-full items-center justify-center rounded border border-slate-200 bg-slate-50 text-slate-400">
      Loading map…
    </div>
  );
}

function Chip({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="text-sm font-medium text-slate-900">{value}</div>
    </div>
  );
}

export default function StreamDetailPage({ params }: { params: { id: string } }) {
  const streamId = Number(params.id);

  const [stream, setStream] = useState<Stream | null>(null);
  const [projection, setProjection] = useState<ProjectionDetail | null>(null);
  const [projectionHistory, setProjectionHistory] =
    useState<ProjectionSeries | null>(null);
  const [rainfall, setRainfall] = useState<RainfallSeries | null>(null);
  const [readings, setReadings] = useState<GaugeReadingSeries | null>(null);
  const [basin, setBasin] = useState<GeoJSON.FeatureCollection | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (Number.isNaN(streamId)) return;
    try {
      const [s, p, ph, rf, rd, all_basins] = await Promise.allSettled([
        apiGet<Stream>(`/api/streams/${streamId}`),
        apiGet<ProjectionDetail>(`/api/streams/${streamId}/projection`),
        apiGet<ProjectionSeries>(
          `/api/streams/${streamId}/projections?hours=${HOURS}`
        ),
        apiGet<RainfallSeries>(
          `/api/streams/${streamId}/rainfall?hours=${HOURS}`
        ),
        apiGet<GaugeReadingSeries>(
          `/api/streams/${streamId}/gauge_readings?parameters=00060,00065&hours=${HOURS}`
        ),
        apiGet<GeoJSON.FeatureCollection>(`/api/basins`),
      ]);

      if (s.status === "fulfilled") setStream(s.value);
      if (p.status === "fulfilled") setProjection(p.value);
      if (ph.status === "fulfilled") setProjectionHistory(ph.value);
      if (rf.status === "fulfilled") setRainfall(rf.value);
      if (rd.status === "fulfilled") setReadings(rd.value);
      if (all_basins.status === "fulfilled") {
        // Filter to just this stream's basin for the inset map.
        const filtered = {
          ...all_basins.value,
          features: all_basins.value.features.filter(
            (f) => f.properties?.stream_id === streamId
          ),
        };
        setBasin(filtered);
      }

      const failures = [s, p, ph, rf, rd, all_basins]
        .filter((r): r is PromiseRejectedResult => r.status === "rejected")
        .map((r) => String(r.reason));
      // The detail page shows partial data freely — only surface a top-level
      // error if everything failed.
      if (s.status === "rejected") setError(String(s.reason));
      else if (failures.length === 6) setError(failures.join("; "));
      else setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [streamId]);

  useEffect(() => {
    load();
    const handle = setInterval(load, REFRESH_MS);
    return () => clearInterval(handle);
  }, [load]);

  if (Number.isNaN(streamId)) {
    return <div className="text-slate-600">Invalid stream id.</div>;
  }

  if (error && !stream) {
    return (
      <div className="space-y-4">
        <Link href="/" className="text-sm text-slate-600 hover:underline">
          ← Back
        </Link>
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      </div>
    );
  }

  if (!stream) {
    return <div className="text-slate-500">Loading…</div>;
  }

  const onStreamGauge = stream.gauges.find(
    (g) => g.relationship === "on_stream"
  );

  return (
    <main className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-slate-600 hover:underline">
          ← Back to watch list
        </Link>
      </div>

      <header className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold sm:text-2xl">{stream.name}</h1>
          {onStreamGauge && (
            <p className="text-sm text-slate-600">
              Gauge {onStreamGauge.usgs_site_id} · {onStreamGauge.name}
            </p>
          )}
        </div>
        <ClarityBadge
          cls={stream.clarity_class}
          confidence={stream.clarity_confidence}
          size="lg"
        />
      </header>

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        <Chip
          label="Basin"
          value={
            stream.basin_area_km2 != null
              ? `${stream.basin_area_km2.toLocaleString(undefined, { maximumFractionDigits: 0 })} km²`
              : null
          }
        />
        <Chip
          label="Row crop"
          value={
            stream.pct_row_crop != null
              ? `${stream.pct_row_crop.toFixed(0)}%`
              : null
          }
        />
        <Chip label="Soil group" value={stream.dominant_hsg} />
        <Chip
          label="Curve number"
          value={
            stream.runoff_curve_number != null
              ? stream.runoff_curve_number.toFixed(0)
              : null
          }
        />
        <Chip
          label="Rain 24h"
          value={
            stream.rainfall_24h_mm != null
              ? `${stream.rainfall_24h_mm.toFixed(1)} mm`
              : null
          }
        />
        <Chip label="DNR class" value={stream.wi_dnr_class} />
      </section>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ChartCard title="Basin rainfall (7d, hourly mm)">
          {rainfall ? (
            <RainfallChart series={rainfall} />
          ) : (
            <ChartEmpty>No rainfall data</ChartEmpty>
          )}
        </ChartCard>
        <ChartCard title="Gauge stage & discharge (7d)">
          {readings && readings.points.length > 0 ? (
            <StageDischargeChart series={readings} />
          ) : (
            <ChartEmpty>No gauge readings</ChartEmpty>
          )}
        </ChartCard>
        <ChartCard title="Projection history (7d)">
          {projectionHistory && projectionHistory.points.length > 0 ? (
            <ProjectionHistoryChart series={projectionHistory} />
          ) : (
            <ChartEmpty>No projections yet</ChartEmpty>
          )}
        </ChartCard>
        <ChartCard title="Basin">
          <div className="h-64">
            <BasinsMap
              basins={basin}
              navigateOnClick={false}
              className="h-64 w-full rounded border border-slate-200"
            />
          </div>
        </ChartCard>
      </section>

      {projection && (
        <section className="rounded border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Why this projection?
          </h2>
          <p className="mt-2 text-sm text-slate-700">
            {String(projection.feature_snapshot.rationale ?? "")}
          </p>
          <details className="mt-3 text-xs text-slate-500">
            <summary className="cursor-pointer">Feature snapshot</summary>
            <pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-3 text-[11px] text-slate-700">
              {JSON.stringify(projection.feature_snapshot, null, 2)}
            </pre>
          </details>
          <div className="mt-2 text-xs text-slate-400">
            Model {projection.model_version} · computed{" "}
            {new Date(projection.computed_at).toLocaleString()}
          </div>
        </section>
      )}
    </main>
  );
}

function ChartCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded border border-slate-200 bg-white p-3">
      <div className="mb-2 text-sm font-medium text-slate-700">{title}</div>
      {children}
    </div>
  );
}

function ChartEmpty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-64 items-center justify-center text-slate-400">
      {children}
    </div>
  );
}
