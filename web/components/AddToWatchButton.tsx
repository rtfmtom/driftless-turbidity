"use client";

import { useState } from "react";

import { apiPost } from "@/lib/api";
import type { WatchCreateRequest } from "@/lib/types";

type Props = {
  siteId: string;
  gaugeName: string;
  alreadyWatched: boolean;
  onAdded: () => void;
};

export function AddToWatchButton({
  siteId,
  gaugeName,
  alreadyWatched,
  onAdded,
}: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (alreadyWatched) {
    return (
      <span className="inline-flex items-center rounded bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-800">
        Watching
      </span>
    );
  }

  const onClick = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const body: WatchCreateRequest = {
        usgs_site_id: siteId,
        stream_name: gaugeName,
      };
      await apiPost("/api/watch", body);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={submitting}
        className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700 disabled:bg-slate-400"
      >
        {submitting ? "Adding…" : "Add to watch"}
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  );
}
