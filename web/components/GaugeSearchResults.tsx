"use client";

import { AddToWatchButton } from "@/components/AddToWatchButton";
import type { GaugeSearchResult } from "@/lib/types";

type Props = {
  results: GaugeSearchResult[];
  onAdded: () => void;
};

export function GaugeSearchResults({ results, onAdded }: Props) {
  if (results.length === 0) {
    return (
      <div className="rounded border border-slate-200 bg-white p-4 text-slate-500">
        No results. Try a different bounding box or parameter.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-100 text-left text-slate-600">
          <tr>
            <th className="px-3 py-2">Site ID</th>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Lat</th>
            <th className="px-3 py-2">Lon</th>
            <th className="px-3 py-2">Parameters</th>
            <th className="px-3 py-2">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {results.map((r) => (
            <tr key={r.usgs_site_id}>
              <td className="px-3 py-2 font-mono">{r.usgs_site_id}</td>
              <td className="px-3 py-2">{r.name}</td>
              <td className="px-3 py-2 tabular-nums">
                {r.latitude?.toFixed(4) ?? "—"}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {r.longitude?.toFixed(4) ?? "—"}
              </td>
              <td className="px-3 py-2 text-xs text-slate-600">
                {r.parameter_codes.slice(0, 6).join(", ") || "—"}
                {r.parameter_codes.length > 6 ? "…" : ""}
              </td>
              <td className="px-3 py-2">
                <AddToWatchButton
                  siteId={r.usgs_site_id}
                  gaugeName={r.name}
                  alreadyWatched={r.already_watched}
                  onAdded={onAdded}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
