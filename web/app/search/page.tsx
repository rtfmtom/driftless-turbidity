"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { BboxForm, DRIFTLESS_DEFAULT, type BboxValues } from "@/components/BboxForm";
import { GaugeSearchResults } from "@/components/GaugeSearchResults";
import { apiGet } from "@/lib/api";
import type { GaugeSearchResult } from "@/lib/types";

export default function SearchPage() {
  const [results, setResults] = useState<GaugeSearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastQuery, setLastQuery] = useState<{
    bbox: BboxValues;
    parameterCode: string;
  } | null>(null);

  const runSearch = useCallback(
    async (bbox: BboxValues, parameterCode: string) => {
      setLoading(true);
      setError(null);
      try {
        const qs = new URLSearchParams({
          bbox: `${bbox.west},${bbox.south},${bbox.east},${bbox.north}`,
          parameter_code: parameterCode,
        });
        const data = await apiGet<GaugeSearchResult[]>(
          `/api/gauges/search?${qs.toString()}`
        );
        setResults(data);
        setLastQuery({ bbox, parameterCode });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const onAdded = useCallback(() => {
    if (lastQuery) runSearch(lastQuery.bbox, lastQuery.parameterCode);
  }, [lastQuery, runSearch]);

  return (
    <main className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Add a gauge</h1>
          <p className="text-sm text-slate-600">
            Search USGS NWIS by bounding box. The default box covers the
            Driftless Area.
          </p>
        </div>
        <Link
          href="/"
          className="rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100"
        >
          ← Back to watch list
        </Link>
      </header>

      <BboxForm
        initial={DRIFTLESS_DEFAULT}
        onSubmit={runSearch}
        disabled={loading}
      />

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading && (
        <div className="rounded border border-slate-200 bg-white p-4 text-slate-500">
          Searching USGS…
        </div>
      )}

      {results !== null && !loading && (
        <GaugeSearchResults results={results} onAdded={onAdded} />
      )}
    </main>
  );
}
