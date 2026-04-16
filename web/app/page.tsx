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

function MapPlaceholder() {
  return (
    <div className="flex h-[60vh] w-full items-center justify-center rounded border border-slate-200 bg-slate-50 text-slate-400">
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
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">
            Driftless Clarity — Watch List
          </h1>
          <p className="text-sm text-slate-600">
            Live USGS readings refresh every minute. Click a basin to drill in.
          </p>
        </div>
        <Link
          href="/search"
          className="rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700"
        >
          Add a gauge
        </Link>
      </header>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          Failed to load: {error}
        </div>
      )}

      <BasinsMap basins={basins} />

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
