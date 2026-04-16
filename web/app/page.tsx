"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";

import { StreamTable } from "@/components/StreamTable";
import { apiGet } from "@/lib/api";
import type { Stream } from "@/lib/types";

// MapLibre touches `window` on import, so load the map only on the client.
const BasinsMap = dynamic(
  () => import("@/components/BasinsMap").then((m) => m.BasinsMap),
  { ssr: false, loading: () => <MapPlaceholder /> }
);

const REFRESH_MS = 60_000;

const MAP_CLASS =
  "h-[45vh] min-h-[280px] w-full rounded border border-slate-200 sm:h-[55vh] lg:h-[60vh]";

function MapPlaceholder() {
  return (
    <div
      className={`${MAP_CLASS} flex items-center justify-center bg-slate-50 text-slate-400`}
    >
      Loading map…
    </div>
  );
}

export default function HomePage() {
  const [streams, setStreams] = useState<Stream[] | null>(null);
  const [basins, setBasins] = useState<GeoJSON.FeatureCollection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const load = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([
        apiGet<Stream[]>("/api/streams"),
        apiGet<GeoJSON.FeatureCollection>("/api/basins"),
      ]);
      setStreams(s);
      setBasins(b);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const handle = setInterval(load, REFRESH_MS);
    return () => clearInterval(handle);
  }, [load]);

  return (
    <main className="space-y-4">
      <header className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-semibold sm:text-2xl">
            Driftless Clarity — Watch List
          </h1>
          <p className="text-sm text-slate-600">
            Live USGS readings refresh every minute. Tap a basin to drill in.
          </p>
        </div>
        <Link
          href="/search"
          className="w-full rounded bg-slate-900 px-3 py-2.5 text-center text-sm text-white hover:bg-slate-700 sm:w-auto"
        >
          Add a gauge
        </Link>
      </header>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          Failed to load: {error}
        </div>
      )}

      <BasinsMap basins={basins} className={MAP_CLASS} />

      {loading && streams === null ? (
        <div className="rounded border border-slate-200 bg-white p-6 text-slate-500">
          Loading…
        </div>
      ) : (
        <StreamTable streams={streams ?? []} />
      )}
    </main>
  );
}
