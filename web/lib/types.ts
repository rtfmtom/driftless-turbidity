// Shapes mirror the Pydantic response models in api/src/driftless/schemas/.

export type Reading = {
  parameter_code: string;
  ts: string;
  value: number | null;
  qualifier: string | null;
};

export type Gauge = {
  usgs_site_id: string;
  name: string;
  relationship: string;
  latest_readings: Reading[];
};

export type ClarityClass = "clear" | "tinged" | "stained" | "blown";
export type ClarityConfidence = "low" | "medium" | "high";

export type Stream = {
  id: number;
  name: string;
  wi_dnr_class: string | null;
  is_watched: boolean;
  basin_area_km2: number | null;
  pct_row_crop: number | null;
  runoff_curve_number: number | null;
  dominant_hsg: string | null;
  rainfall_24h_mm: number | null;
  clarity_class: ClarityClass | null;
  clarity_confidence: ClarityConfidence | null;
  clarity_computed_at: string | null;
  gauges: Gauge[];
};

export type GaugeSearchResult = {
  usgs_site_id: string;
  name: string;
  latitude: number | null;
  longitude: number | null;
  parameter_codes: string[];
  already_watched: boolean;
};

export type WatchCreateRequest = {
  usgs_site_id: string;
  stream_name?: string;
  relationship?: string;
};
