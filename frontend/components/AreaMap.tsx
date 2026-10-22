"use client";

import type { Feature, Point } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MLMap, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { AreaResult, AreaSensorProps, AreaSource, MapDefaults } from "@/lib/api";
import { shortDate, type BBox } from "@/lib/area";

type Props = {
  area: AreaResult | null;
  initialView?: MapDefaults | null; // region's starting view, used until an area is loaded
  onView: (bounds: BBox) => void; // current visible box, reported after each move
};

const FALLBACK_VIEW = { center: [-74.39, 40.53] as [number, number], zoom: 11.6 };
const BASEMAP = "https://tiles.openfreemap.org/styles/dark";
const EMPTY = { type: "FeatureCollection" as const, features: [] as Feature[] };

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function popupHtml(p: AreaSensorProps, sources: AreaSource[]) {
  const src = sources.find((s) => s.id === p.source);
  const dirs: number[] = typeof p.directions_deg === "string" ? JSON.parse(p.directions_deg) : p.directions_deg ?? [];
  const dir = dirs.length
    ? `faces ${dirs.map((d) => `${Math.round(d)}°`).join(", ")}`
    : p.direction_raw ? `direction "${esc(p.direction_raw)}" (not a compass bearing)` : "direction not recorded";
  const edited = shortDate(p.last_edited);
  return `<div class="pop-title">Fixed sensor</div>`
    + `<div class="pop-row">${dir}</div>`
    + `<div class="pop-sep pop-dim">source: ${esc(src?.name ?? p.source)}</div>`
    + (edited ? `<div class="pop-dim">last edited in OSM: ${edited}</div>` : "")
    + `<div class="pop-dim">${esc(p.id)}</div>`;
}

/** Map for the Explore view: the explored box and the public sensors inside it. */
export default function AreaMap({ area, initialView = null, onView }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const latest = useRef({ area, onView });
  latest.current = { area, onView };

  useEffect(() => {
    if (!el.current) return;
    maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");
    const m = new maplibregl.Map({
      container: el.current,
      style: BASEMAP,
      center: FALLBACK_VIEW.center,
      zoom: FALLBACK_VIEW.zoom,
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");
    const report = () => {
      const b = m.getBounds();
      latest.current.onView([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
    };
    m.on("moveend", report);
    m.on("load", () => {
      m.addSource("area-box", { type: "geojson", data: EMPTY });
      m.addSource("area-sensors", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "area-box-fill", type: "fill", source: "area-box", paint: { "fill-color": "#e8e2d4", "fill-opacity": 0.03 } });
      m.addLayer({
        id: "area-box-line", type: "line", source: "area-box",
        paint: { "line-color": "#e8e2d4", "line-width": 1.2, "line-dasharray": [3, 2], "line-opacity": 0.7 },
      });
      m.addLayer({
        id: "area-sensors", type: "circle", source: "area-sensors",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 3.5, 15, 7],
          "circle-color": ["case", ["get", "has_direction"], "#f2a541", "#0b0d0e"],
          "circle-stroke-color": "#f2a541",
          "circle-stroke-width": 1.5,
        },
      });
      const popup = new maplibregl.Popup({ className: "pt-popup", maxWidth: "260px" });
      m.on("click", "area-sensors", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        if (!f) return;
        popup.setLngLat((f.geometry as Point).coordinates as [number, number])
          .setHTML(popupHtml(f.properties as unknown as AreaSensorProps, latest.current.area?.summary.sources ?? [])).addTo(m);
      });
      m.on("mouseenter", "area-sensors", () => { m.getCanvas().style.cursor = "pointer"; });
      m.on("mouseleave", "area-sensors", () => { m.getCanvas().style.cursor = ""; });
      setReady(true);
      report();
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  // Region's starting view, only while no area is shown.
  useEffect(() => {
    if (!ready || area || !initialView) return;
    const { bounds, center, zoom } = initialView;
    if (bounds) map.current!.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: 40, duration: 0 });
    else if (center) map.current!.jumpTo({ center, zoom: zoom ?? FALLBACK_VIEW.zoom });
  }, [ready, area, initialView]);

  useEffect(() => {
    if (!ready) return;
    const m = map.current!;
    const box = m.getSource("area-box") as GeoJSONSource;
    const sensors = m.getSource("area-sensors") as GeoJSONSource;
    if (!area) {
      box.setData(EMPTY);
      sensors.setData(EMPTY);
      return;
    }
    const [w, s, e, n] = area.bbox;
    box.setData({
      type: "Feature", properties: {},
      geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
    });
    sensors.setData({
      ...EMPTY,
      features: area.sensors.features.map((f) => ({
        ...f, properties: { ...f.properties, has_direction: !!f.properties.directions_deg?.length },
      })),
    });
    m.fitBounds([[w, s], [e, n]], { padding: 40, duration: 600 });
  }, [ready, area]);

  return <div ref={el} className="map" role="region" aria-label="Map of the explored area" />;
}
