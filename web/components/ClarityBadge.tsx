import type { ClarityClass, ClarityConfidence } from "@/lib/types";

export const CLARITY_HEX: Record<ClarityClass, string> = {
  clear: "#10b981",   // emerald-500
  tinged: "#eab308",  // yellow-500
  stained: "#f97316", // orange-500
  blown: "#ef4444",   // red-500
};

const CLARITY_STYLE: Record<ClarityClass, string> = {
  clear: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  tinged: "bg-yellow-100 text-yellow-800 ring-yellow-200",
  stained: "bg-orange-100 text-orange-800 ring-orange-200",
  blown: "bg-red-100 text-red-800 ring-red-200",
};

export function ClarityBadge({
  cls,
  confidence,
  size = "sm",
}: {
  cls: ClarityClass | null;
  confidence?: ClarityConfidence | null;
  size?: "sm" | "lg";
}) {
  if (!cls) {
    return <span className="text-slate-400">—</span>;
  }
  const padding = size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs";
  return (
    <div className="flex flex-col gap-0.5">
      <span
        className={`inline-flex w-fit items-center rounded font-semibold uppercase tracking-wide ring-1 ring-inset ${CLARITY_STYLE[cls]} ${padding}`}
      >
        {cls}
      </span>
      {confidence && (
        <span className="text-xs text-slate-400">{confidence} confidence</span>
      )}
    </div>
  );
}
