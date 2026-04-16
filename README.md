# Driftless Clarity Dashboard — Build Plan

> A personal monitoring and projection tool for stream turbidity and water clarity across a user-configurable watch list of Driftless Area streams. The system ingests public rainfall and streamflow data, computes basin-averaged precipitation, and produces next-morning clarity projections with confidence bands.

## 1. Objective

Build a web-based dashboard that answers one question at a time, per stream, every morning: **how turbid is this water right now, and how is it trending over the next 12–36 hours?**

The system treats clarity as a function of:
- rainfall intensity and depth over the specific upstream basin (1, 6, 24, 72 hours back)
- antecedent basin wetness
- basin characteristics (drainage area, land cover mix, baseflow index, slope)
- nearest gauged analog behavior

It explicitly does *not* make recommendations about activities. It reports water conditions.

## 2. Scope

**In scope (v1):**
- User-configurable watch list of streams (initial seed: West Fork Kickapoo, Timber Coulee, Tainter Creek, Coon Creek, Bad Axe, Maple Dale, and 10–20 user-specified headwater tributaries)
- Automated ingestion of USGS streamflow/stage, USGS direct turbidity where available, and NOAA MRMS gridded precipitation
- Basin polygons computed once and cached (with tooling to recompute on demand)
- A projection engine that produces a categorical clarity estimate per stream with confidence
- A map-based dashboard with stream detail pages
- A manual observation log so the user can record ground truth when scouting and tune the model over time

**Out of scope (v1):**
- Mobile-native app (responsive web is fine)
- Notifications/alerts (Phase 5)
- Multi-user accounts (single-user system)
- Anything outside the Driftless Area

## 3. Recommended Tech Stack

Pick these unless there's a strong reason to deviate.

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Geospatial and hydrology libs are Python-first |
| DB | PostgreSQL 16 + PostGIS | Spatial queries on basins, raster-clipping support |
| Scheduler | APScheduler (in-process) or systemd timers | No need for Celery/Redis at this scale |
| Geospatial | GeoPandas, Rasterio, Shapely, `pynhd`, `py3dep`, `dataretrieval` | All maintained by USGS or the geospatial community |
| Raster handling | xarray + rioxarray for MRMS GRIB2 | Clean slicing and basin-clipping |
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind | Clean SSR, good map integration |
| Mapping | MapLibre GL JS with vector tiles | Free, performant, no Mapbox token needed |
| Charts | Recharts or Visx | Straightforward time-series |
| Deployment | Docker Compose on a small VPS (Hetzner, Fly.io) | ~$10/mo, full control |

If deployment simplicity is valued over polish, **Streamlit** or **Dash** would collapse the frontend into Python and ship in half the time, at the cost of a less distinctive UI. Flag this as a decision point before Phase 1.

## 4. Data Sources

Each source has a dedicated ingestion module with its own schedule, retry logic, and local cache.

### 4.1 USGS NWIS (Real-Time Streamflow & Stage)
- **API:** `https://waterservices.usgs.gov/nwis/iv/` (instantaneous values) and `/dv/` (daily values), JSON format
- **Python client:** `dataretrieval` package (official USGS)
- **Cadence:** Poll every 15 minutes for real-time; nightly backfill of daily values
- **Key parameter codes:** `00060` (discharge, cfs), `00065` (gauge height, ft), `00010` (water temp), `63680` (turbidity, FNU) where available
- **Seed sites for Driftless:**
  - `05407470` Kickapoo River at Ontario
  - `05408000` Kickapoo River at La Farge
  - `05408476` West Fork Kickapoo at Cashton
  - `05409000` West Fork Kickapoo near Readstown
  - `05388250` Upper Iowa near Dorchester (analog for southern tier)
  - User should be able to add more via a site-search UI

### 4.2 USGS National Real-Time Water Quality (NRTWQ)
- **Site:** `nrtwq.usgs.gov`
- **Use:** Where continuous turbidity sensors exist, pull hourly computed sediment concentrations as ground truth for model calibration
- **Cadence:** Hourly

### 4.3 NOAA MRMS QPE (Gridded Rainfall)
- **Primary source:** AWS open data bucket `s3://noaa-mrms-pds/` (no auth required)
- **Product to start with:** `MultiSensor_QPE_01H_Pass2` (1-hour multi-sensor QPE, gauge-corrected)
- **Format:** GRIB2, 1 km CONUS grid
- **Cadence:** Hourly ingest; retain rolling 30 days at full resolution, aggregate older data to daily sums
- **Processing:** On ingest, clip each grid to each basin polygon with a ~2-mile buffer, compute area-weighted mean rainfall, store per-basin per-hour totals in Postgres

### 4.4 NOAA NWS / AHPS
- **Site:** `water.weather.gov`
- **Use:** Short-range stage forecasts for gauged rivers (sanity check and direct feature for mainstem stations)
- **Cadence:** Every 3 hours

### 4.5 USGS Watershed & Hydrography Data (One-Time + On-Demand)
- **WBD (Watershed Boundary Dataset):** HUC12 polygons — coarse basin reference
- **NHDPlus HD:** Stream network and catchment polygons — the right resolution for Driftless tribs
- **3DEP DEM (1 m or 10 m):** For custom basin delineation when NHD catchments are too large
- **Python tooling:** `pynhd` (NHDPlus access), `py3dep` (DEM access), `pygeohydro` (general USGS wrapper)
- **Cadence:** One-time fetch per stream, cache the basin polygon in Postgres

### 4.6 Land Cover & Soils (Static Layers)
- **NLCD 2021** (National Land Cover Database) — 30 m raster, pull once, compute per-basin % row crop / % forest / % developed / % pasture
- **SSURGO soils** — compute per-basin hydrologic soil group distribution (used for runoff curve number estimation)
- **Sources:** MRLC Consortium for NLCD; USDA NRCS Web Soil Survey for SSURGO

### 4.7 Wisconsin DNR Trout Stream Layer
- **Source:** `apps.dnr.wi.gov/water/troutlist`
- **Use:** Enrich each stream record with classification (Class I/II/III) and known regulations; not used in the model itself but helpful UI context

## 5. Data Model (Postgres Schema)

```sql
-- Reference entities
streams               (id, name, waterbody_type, wi_dnr_class, notes, is_watched)
basins                (id, stream_id, polygon GEOMETRY, area_km2, computed_at)
basin_characteristics (basin_id, pct_row_crop, pct_forest, pct_pasture, pct_developed,
                       baseflow_index, mean_slope, dominant_hsg, runoff_curve_number)
gauges                (usgs_site_id, name, location GEOMETRY, parameters_available JSONB)
stream_gauge_links    (stream_id, usgs_site_id, relationship,  -- 'on_stream' | 'analog'
                       distance_km, similarity_score)

-- Observations (time-series)
gauge_readings        (gauge_id, ts, parameter_code, value, qualifier)  -- partitioned monthly
basin_rainfall        (basin_id, ts, rainfall_mm, source)  -- hourly MRMS-derived
stage_forecasts       (gauge_id, forecast_ts, target_ts, stage_ft, source)

-- Model outputs
projections           (stream_id, computed_at, valid_from, valid_to,
                       clarity_class, confidence, feature_snapshot JSONB,
                       model_version)

-- Ground truth
field_observations    (stream_id, observed_at, clarity_class, stage_estimate,
                       photo_path, notes, entered_at)
```

Clarity classes (categorical, ordered): `clear` | `tinged` | `stained` | `blown`. Keep the vocabulary tight — this is the model's output and the user's input format, so they must match exactly.

## 6. Projection Engine

Build this in three layers, each of which is independently useful.

### Layer A — Feature Computation
For each stream, compute a feature vector every hour (or on-demand for the dashboard):
- `rainfall_1h`, `rainfall_6h`, `rainfall_24h`, `rainfall_72h` (basin-averaged, from MRMS)
- `antecedent_wetness` (7-day basin rainfall)
- `nearest_gauge_stage_current`, `nearest_gauge_stage_delta_6h`
- Static basin features (looked up, not recomputed): drainage area, % row crop, baseflow index, mean slope, runoff curve number

### Layer B — Baseline Heuristic Model (Ship in Phase 3)
A rules-based model that encodes the physical intuition and works immediately without training data:

```
if rainfall_24h < 5mm and stage_delta_6h < +0.2ft:
    clarity = clear (confidence high)
elif rainfall_24h < 15mm and pct_row_crop < 30% and baseflow_index > 0.6:
    clarity = tinged (confidence medium)
elif rainfall_24h < 30mm:
    clarity = stained (confidence medium)
else:
    clarity = blown (confidence high)
```

The thresholds above are placeholders. Calibrate them against historical NRTWQ turbidity observations for the nearest instrumented station during the backfill step (see Phase 2).

### Layer C — Analog Model (Phase 4+)
Once there are ≥90 days of ingested data and ≥20 ground-truth observations:
- For each projection, find the K nearest historical feature-vector neighbors at gauged streams with turbidity sensors
- Use the historical clarity distribution of those neighbors as the projection
- Prefer this over the heuristic model when K-NN distance is below a threshold; fall back to heuristic otherwise

This keeps the system useful from day one and improves as data accumulates.

## 7. Frontend / Dashboard

### 7.1 Main View — Watch List Map
- MapLibre map centered on the Driftless region, zoomed to the user's watch list extent
- Stream lines color-coded by current projection: green (clear) → yellow (tinged) → orange (stained) → red (blown), with gray for "no recent data"
- Optional MRMS 24-hour rainfall raster overlay, toggleable
- Sidebar list of watched streams, each row showing name, current class, 24-hour rainfall, trend arrow

### 7.2 Stream Detail Page
- Header: stream name, current clarity class, confidence, basin area, % row crop, DNR class
- Charts (past 7 days):
  - Basin-averaged hourly rainfall (bar)
  - Nearest gauge stage/discharge (line)
  - Direct turbidity if available (line)
  - Projection history (stepped line colored by class)
- Basin map inset with MRMS rainfall overlay for the last 24 hours
- "Log observation" button that opens a modal to record field-observed clarity

### 7.3 Observation Log
- Simple table + entry form
- Phone-friendly layout so observations can be logged from the field
- Each logged observation is a training signal for future model calibration

## 8. Build Phases

Each phase is independently shippable and testable.

### Phase 1 — Skeleton & USGS Ingest (target: 1–2 evenings)
- Repo, Docker Compose, Postgres+PostGIS, FastAPI, Next.js scaffold
- `streams`, `gauges`, `gauge_readings` tables
- USGS NWIS ingestion for 5 seed gauges, every 15 minutes
- Minimal dashboard: list of watched streams with most-recent stage and discharge
- **Exit criteria:** Can see live USGS data updating in the UI

### Phase 2 — Basin Delineation & MRMS (target: 2–3 evenings)
- Add `basins`, `basin_characteristics`, `basin_rainfall` tables
- One-time basin computation pipeline using `pynhd` + `py3dep` with manual review/override
- NLCD and SSURGO feature extraction per basin
- MRMS hourly ingest from AWS, basin-clipped, stored as hourly per-basin totals
- Backfill MRMS and USGS for the prior 90 days
- **Exit criteria:** Each watched stream has a cached basin polygon, computed characteristics, and 90 days of hourly rainfall history

### Phase 3 — Heuristic Projection & Map UI (target: 2–3 evenings)
- Implement Layer A feature computation
- Implement Layer B heuristic model
- `projections` table and hourly projection job
- Map view with color-coded streams and stream detail pages
- **Exit criteria:** Opening the dashboard in the morning shows a clarity projection per watched stream with supporting rainfall/stage context

### Phase 4 — Observation Log & Calibration Loop (target: 1–2 evenings)
- `field_observations` table and entry form
- Mobile-friendly observation entry route
- Script that recalibrates heuristic thresholds against logged observations (run manually initially)
- **Exit criteria:** Field observations can be logged, and there's a repeatable process for tuning the model against them

### Phase 5 — Analog Model & Notifications (target: 3–4 evenings, deferred until data accumulates)
- Layer C K-NN analog model
- Optional: email or Pushover notification when any watched stream transitions from `blown`/`stained` to `tinged`/`clear`
- **Exit criteria:** Analog model is serving projections where the heuristic confidence is low, and the user receives a morning summary

## 9. Repo Layout

```
driftless-clarity/
├── docker-compose.yml
├── .env.example
├── api/                      # FastAPI service
│   ├── pyproject.toml
│   ├── src/driftless/
│   │   ├── db/               # SQLAlchemy models + Alembic migrations
│   │   ├── ingest/
│   │   │   ├── usgs.py
│   │   │   ├── mrms.py
│   │   │   ├── ahps.py
│   │   │   └── nlcd_ssurgo.py
│   │   ├── basins/
│   │   │   ├── delineate.py  # pynhd + py3dep wrappers
│   │   │   └── characterize.py
│   │   ├── projection/
│   │   │   ├── features.py
│   │   │   ├── heuristic.py
│   │   │   └── analog.py
│   │   ├── api/              # FastAPI routers
│   │   └── scheduler.py      # APScheduler job definitions
│   └── tests/
├── web/                      # Next.js app
│   ├── package.json
│   ├── app/
│   │   ├── page.tsx          # Map dashboard
│   │   ├── streams/[id]/     # Stream detail
│   │   └── observations/     # Log entry
│   └── components/
└── data/                     # Gitignored; mounted volume for raster cache
```

## 10. Operational Notes

- **MRMS storage:** Hourly GRIB2 files are ~10 MB each. 30 days = ~7 GB. Budget accordingly, and clip aggressively to a Driftless bounding box on ingest rather than storing full CONUS.
- **Basin delineation quality:** The NHDPlus HD catchments work well for most Driftless streams, but small spring-fed headwaters sometimes get lumped into an upstream catchment. Build in a manual override where a user-provided point snaps to the nearest flowline and a custom basin is delineated via `py3dep` pour-point analysis.
- **Cold-start problem:** The heuristic model ships with placeholder thresholds. Phase 2's 90-day backfill is what makes the heuristic usable — run it once and spot-check the thresholds against what the user remembers about recent conditions.
- **Model honesty:** Every projection in the UI should show its feature snapshot and confidence. If the user can see *why* the model is calling a stream "stained," they can override it and log the real observation. That feedback loop is the entire point.
- **API rate limits:** USGS NWIS is generous but not infinite. Batch site requests (one call per watched gauge list, not one per gauge) and respect 15-minute minimum cadence.

## 11. Initial Tasks for Claude Code

Hand Claude Code these in order:

1. Scaffold the repo per the layout above, with Docker Compose for Postgres+PostGIS and a FastAPI "hello world" route.
2. Define the Phase 1 tables as Alembic migrations. Include the PostGIS extension.
3. Implement `ingest/usgs.py` using the `dataretrieval` package. Pull instantaneous values for five hardcoded Driftless gauges. Write a CLI entrypoint (`python -m driftless.ingest.usgs`) and an APScheduler job for 15-minute cadence.
4. Scaffold the Next.js app with a single page that fetches `/api/streams` and renders a table of the most recent gauge readings per stream.
5. Add a simple site-search UI that queries USGS NWIS for gauges within a bounding box and lets the user add them to the watch list.

After Phase 1 is working, continue with Phase 2 — the MRMS ingest and basin delineation are the hardest pieces, so give them a full evening each.

## 12. Success Criteria for v1

- The user wakes up, opens the dashboard from their phone, and sees a color-coded map of 15–25 Driftless streams with current clarity projections.
- Tapping a stream shows a 7-day history of rainfall, stage, and projection class.
- A log entry takes less than 15 seconds to submit from the field.
- The system runs unattended for a full month without manual intervention.
- After one season of use, the logged observations produce visible improvements in projection accuracy through threshold recalibration.
