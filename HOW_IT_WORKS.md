# How the Driftless Clarity Dashboard Works

A plain-language overview of what the app does, what data it uses, and
how it decides how clear each stream is likely to be.

---

## The question it answers

For each stream on the watch list, every hour:

> **How turbid is this water right now, and how is it likely to trend
> over the next several hours?**

The answer is one of four categories — **clear**, **tinged**,
**stained**, **blown** — along with a confidence level (low / medium /
high) and a short explanation of *why* the app landed on that call.

The app does not recommend whether to fish, wade, paddle, or anything
else. It just reports the water conditions.

---

## What it watches

The current watch list is three gauges on the Kickapoo River
(La Farge, Ontario, Steuben). Adding a new stream is a matter of
picking a USGS gauge from a search box — the app handles the rest.

For every watched stream the app keeps track of the **upstream basin** —
the land area that drains into it. Everything the app does is
basin-specific, because a thunderstorm five miles away doesn't matter
unless it fell *on the land that feeds this stream*.

---

## What data the app pulls in

Everything comes from free public sources; nothing is scraped or paid
for.

### 1. Streamflow and stage, from USGS

Every 15 minutes the app asks the U.S. Geological Survey for the
latest readings at each gauge:

- Discharge (how much water is flowing, in cubic feet per second)
- Gauge height / stage (how high the water is, in feet)
- Water temperature
- Turbidity itself, at the handful of stations that directly measure it

### 2. Rainfall, from NOAA

Once an hour the app downloads a national rainfall map from NOAA's
MRMS system (a gauge-corrected radar estimate at ~1 km resolution),
trims it to the Driftless region, and figures out how much rain fell
**on each watched basin** over the last hour. Ninety days of history
was backfilled when the app went live, so the long-term running
totals are meaningful right away.

### 3. The shape of each basin, from USGS

The first time a stream is added, the app asks USGS for the exact
outline of the land draining into that gauge. This is stored
permanently and used to compute basin-average rainfall, land cover,
and so on.

### 4. What the basin is made of

Also a one-time pull per basin, from a handful of federal datasets:

- **Land cover** — what percent is row crops, forest, pasture,
  developed land, or wetland (from the National Land Cover Database)
- **Soil type** — dominant hydrologic soil group A/B/C/D (from USDA's
  soil survey)
- **Runoff tendency** — a standard "curve number" combining land
  cover and soil, where higher = more runoff per inch of rain
- **Slope** — average steepness (from USGS elevation data)

These don't change on a short timescale, so they're only fetched
once per basin (and can be re-pulled on demand).

---

## How it decides the clarity category

The current model is a **rules-based decision tree** — a short list
of physically-motivated "if / then" checks, applied in order.
The first rule that matches wins. This keeps the logic transparent
and makes it easy to see why any given call was made.

The rules look at three things:

1. **How much rain fell on this basin in the last 24 hours**
2. **Whether the stream's stage is rising right now**
3. **What kind of basin it is** — mostly row crop vs. mostly forest/
   pasture, and whether the baseflow signal is strong

In plain English, the rules are:

| Category | Fires when … |
|---|---|
| **Clear** | Less than about 5 mm of rain in the last 24 h **and** the stream's stage isn't rising. |
| **Tinged** | Less than about 15 mm of rain in the last 24 h **and** the basin is mostly forest or pasture (row crop under ~30 %). |
| **Stained** | Between roughly 15 and 30 mm of rain in the last 24 h. |
| **Blown** | More than about 30 mm of rain in the last 24 h — the basin is loaded and the stream will be muddy. |

If rainfall data is missing for some reason, the app defaults to
**stained** with low confidence rather than guessing.

Every projection is stored with the inputs that drove it (rain total,
stage change, land-cover mix, etc.) and a one-line rationale, so the
stream detail page can say "tinged because 24 h rainfall was 7.8 mm
and row crop is only 11 %" — not just emit a label.

### Why a rules-based model?

Two reasons:

- **We don't have enough ground-truth observations yet to train a
  statistical model.** A rules model makes the assumptions explicit
  and adjustable.
- **It's inspectable.** When the app is wrong, it's obvious *why* —
  which directly suggests how to fix the thresholds.

The thresholds above are **starting values**. The intent is that as we
start logging actual observations ("went out today, water looked
stained"), we'll calibrate them against reality. The long-term path
is to keep the rules model as a transparent baseline and layer a
data-driven model on top once there's enough logged data to train one.

---

## What runs when

Three things happen automatically:

1. **Every 15 minutes** — pull the latest streamflow and stage numbers
   from USGS.
2. **Every hour, at :15 past** — pull the prior hour's rainfall grid
   from NOAA and compute the per-basin total.
3. **Every hour, at :20 past** — recompute the clarity projection for
   every watched stream, using the rainfall that just landed five
   minutes ago.

Everything else is one-time setup per stream (pulling its basin
outline, characterizing the land) or one-time setup per server
(backfilling historical rainfall).

---

## What this is *not* yet

Things planned but not built:

- **Observation logging** — a way to record "went out to the stream
  today, water looked like X" so the model can be calibrated against
  ground truth. This is the single biggest gap. Phase 4.
- **Alerts / notifications** — the app is a dashboard you check, not
  a thing that pings you.
- **Multiple users** — it's a single-user tool right now.
- **Anywhere outside the Driftless region** — the data sources are
  national, but the basin list and the rainfall clipping box are
  Driftless-specific.

---

## Operating cost and shape

The whole thing runs on one small VPS. It uses:

- Modest bandwidth (the hourly rainfall grid trimmed to the Driftless
  is a few MB; the rest is tiny JSON calls)
- A modest Postgres database (time-series of readings + rainfall)
- No paid APIs, no cloud-provider lock-in

The site sits behind Cloudflare for caching and TLS. If the VPS
hardware were ever lost, the whole system could be rebuilt from the
code repository plus a fresh Postgres backup in under an hour.
