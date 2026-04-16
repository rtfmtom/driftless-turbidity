"use client";

import { useState } from "react";

export type BboxValues = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export const DRIFTLESS_DEFAULT: BboxValues = {
  west: -92.3,
  south: 42.6,
  east: -90.3,
  north: 44.2,
};

type Props = {
  initial?: BboxValues;
  onSubmit: (bbox: BboxValues, parameterCode: string) => void;
  disabled?: boolean;
};

export function BboxForm({ initial = DRIFTLESS_DEFAULT, onSubmit, disabled }: Props) {
  const [values, setValues] = useState<BboxValues>(initial);
  const [parameterCode, setParameterCode] = useState<string>("00060");

  const set = (k: keyof BboxValues) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseFloat(e.target.value);
    setValues((prev) => ({ ...prev, [k]: Number.isFinite(v) ? v : prev[k] }));
  };

  return (
    <form
      className="rounded border border-slate-200 bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(values, parameterCode);
      }}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(["west", "south", "east", "north"] as const).map((k) => (
          <label key={k} className="flex flex-col text-xs text-slate-600">
            <span className="uppercase tracking-wide">{k}</span>
            <input
              type="number"
              step="0.01"
              inputMode="decimal"
              className="mt-1 w-full rounded border border-slate-300 px-2 py-2 font-mono text-sm"
              value={values[k]}
              onChange={set(k)}
              disabled={disabled}
            />
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col text-xs text-slate-600 sm:max-w-xs">
          <span className="uppercase tracking-wide">Parameter</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-2 text-sm"
            value={parameterCode}
            onChange={(e) => setParameterCode(e.target.value)}
            disabled={disabled}
          >
            <option value="00060">00060 — Discharge</option>
            <option value="00065">00065 — Stage</option>
            <option value="00010">00010 — Water temp</option>
            <option value="63680">63680 — Turbidity</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={disabled}
          className="w-full rounded bg-slate-900 px-3 py-2.5 text-sm text-white hover:bg-slate-700 disabled:bg-slate-400 sm:w-auto"
        >
          Search
        </button>
      </div>
    </form>
  );
}
