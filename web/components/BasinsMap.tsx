"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { CLARITY_HEX } from "@/components/ClarityBadge";

type Props = {
  /** A GeoJSON FeatureCollection from /api/basins. */
  basins: GeoJSON.FeatureCollection | null;
  /** When the user clicks a basin we navigate; opt out by passing false. */
  navigateOnClick?: boolean;
  /** Tailwind height utility (e.g., 'h-[60vh]'). Defaults to a reasonable inline height. */
  className?: string;
  /** Override the default Driftless centering. */
  initialCenter?: [number, number];
  initialZoom?: number;
};

const DRIFTLESS_CENTER: [number, number] = [-90.7, 43.4];
const DRIFTLESS_ZOOM = 8;

const FALLBACK_FILL = "#94a3b8"; // slate-400 — used when no clarity yet

export function BasinsMap({
  basins,
  navigateOnClick = true,
  className = "h-[60vh] w-full rounded border border-slate-200",
  initialCenter = DRIFTLESS_CENTER,
  initialZoom = DRIFTLESS_ZOOM,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const router = useRouter();

  // Initialize the map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      // Inline raster style — OpenStreetMap tiles, no token required.
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
      center: initialCenter,
      zoom: initialZoom,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push basins data into the map whenever it changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !basins) return;

    const apply = () => {
      const fillColor: maplibregl.ExpressionSpecification = [
        "match",
        ["get", "clarity_class"],
        "clear",
        CLARITY_HEX.clear,
        "tinged",
        CLARITY_HEX.tinged,
        "stained",
        CLARITY_HEX.stained,
        "blown",
        CLARITY_HEX.blown,
        FALLBACK_FILL,
      ];

      const existing = map.getSource("basins") as
        | maplibregl.GeoJSONSource
        | undefined;
      if (existing) {
        existing.setData(basins);
      } else {
        map.addSource("basins", { type: "geojson", data: basins });
        map.addLayer({
          id: "basins-fill",
          type: "fill",
          source: "basins",
          paint: {
            "fill-color": fillColor,
            "fill-opacity": 0.45,
          },
        });
        map.addLayer({
          id: "basins-outline",
          type: "line",
          source: "basins",
          paint: {
            // Dark, solid outline so nested basins with the same clarity
            // color still have a visible boundary.
            "line-color": "#1e293b", // slate-800
            "line-width": 1.25,
            "line-opacity": 0.7,
          },
        });

        // Click → navigate to the stream's detail page.
        map.on("click", "basins-fill", (e) => {
          const feature = e.features?.[0];
          const streamId = feature?.properties?.stream_id;
          if (streamId == null) return;
          if (navigateOnClick) router.push(`/streams/${streamId}`);
        });
        map.on("mouseenter", "basins-fill", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "basins-fill", () => {
          map.getCanvas().style.cursor = "";
        });

        // Tooltip popup
        const popup = new maplibregl.Popup({
          closeButton: false,
          closeOnClick: false,
        });
        map.on("mousemove", "basins-fill", (e) => {
          const feature = e.features?.[0];
          if (!feature) return;
          const p = feature.properties as Record<string, unknown>;
          const name = String(p.stream_name ?? "");
          const cls = String(p.clarity_class ?? "—");
          const conf = String(p.confidence ?? "");
          const area = p.area_km2 != null ? Number(p.area_km2) : null;
          popup
            .setLngLat(e.lngLat)
            .setHTML(
              `<div style="font-family:ui-sans-serif;line-height:1.3;font-size:12px">` +
                `<div style="font-weight:600">${escapeHtml(name)}</div>` +
                `<div>${escapeHtml(cls)}${conf ? ` &middot; ${escapeHtml(conf)}` : ""}</div>` +
                (area != null
                  ? `<div style="color:#64748b">basin ${area.toFixed(0)} km²</div>`
                  : "") +
                `</div>`
            )
            .addTo(map);
        });
        map.on("mouseleave", "basins-fill", () => popup.remove());
      }

      // Fit to the basins extent on first load.
      if (basins.features.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        for (const f of basins.features) {
          extendBounds(bounds, f.geometry);
        }
        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, { padding: 40, maxZoom: 10, duration: 0 });
        }
      }
    };

    if (map.isStyleLoaded()) {
      apply();
    } else {
      map.once("load", apply);
    }
  }, [basins, navigateOnClick, router]);

  return <div ref={containerRef} className={className} />;
}

// Bare suffix: avoid pulling in a sanitizer for short tooltip text.
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function extendBounds(bounds: maplibregl.LngLatBounds, geom: GeoJSON.Geometry) {
  if (geom.type === "Polygon") {
    for (const ring of geom.coordinates) {
      for (const [lng, lat] of ring) bounds.extend([lng, lat] as [number, number]);
    }
  } else if (geom.type === "MultiPolygon") {
    for (const poly of geom.coordinates) {
      for (const ring of poly) {
        for (const [lng, lat] of ring) bounds.extend([lng, lat] as [number, number]);
      }
    }
  }
}
