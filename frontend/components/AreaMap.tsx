"use client";

import type { Feature, Point } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLat, Map as MLMap, MapLayerMouseEvent, MapMouseEvent, MapTouchEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { AreaResult, AreaSensorProps, AreaSource, MapDefaults } from "@/lib/api";
import { cornersToBBox, shortDate, type BBox } from "@/lib/area";

type Props = {
  area: AreaResult | null;
  initialView?: MapDefaults | null; // region's starting view, used until an area is loaded
  onView: (bounds: BBox) => void; // current visible box, reported after each move
  drawing?: boolean; // drag on the map draws a box instead of panning
  onDraw?: (box: BBox | null) => void; // drawn box, or null when drawing is cancelled
};

const FALLBACK_VIEW = { center: [-74.39, 40.53] as [number, number], zoom: 11.6 };
const BASEMAP = "https://tiles.openfreemap.org/styles/dark";
const EMPTY = { type: "FeatureCollection" as const, features: [] as Feature[] };
const MIN_DRAW_DEG = 0.002; // smaller drags (about 200 m) are treated as clicks, not boxes

const boxPolygon = ([w, s, e, n]: BBox): Feature => ({
  type: "Feature", properties: {},
  geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
});

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
export default function AreaMap({ area, initialView = null, onView, drawing = false, onDraw }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const latest = useRef({ area, onView, drawing, onDraw });
  latest.current = { area, onView, drawing, onDraw };

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
      m.addSource("draw-box", { type: "geojson", data: EMPTY });
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
      m.addLayer({ id: "draw-box-fill", type: "fill", source: "draw-box", paint: { "fill-color": "#f2a541", "fill-opacity": 0.08 } });
      m.addLayer({ id: "draw-box-line", type: "line", source: "draw-box", paint: { "line-color": "#f2a541", "line-width": 1.5 } });

      // Draw mode: press, drag and release to span a box (mouse or one finger).
      const drawSrc = m.getSource("draw-box") as GeoJSONSource;
      let start: LngLat | null = null;
      let last: LngLat | null = null;
      const corners = (): BBox => cornersToBBox(start!.toArray() as [number, number], last!.toArray() as [number, number]);
      const begin = (e: MapMouseEvent | MapTouchEvent) => {
        if (!latest.current.drawing || ("points" in e && e.points.length > 1)) return;
        e.preventDefault();
        start = last = e.lngLat;
      };
      const drag = (e: MapMouseEvent | MapTouchEvent) => {
        if (!start) return;
        last = e.lngLat;
        drawSrc.setData(boxPolygon(corners()));
      };
      const finish = () => {
        if (!start) return;
        const box = corners();
        start = last = null;
        drawSrc.setData(EMPTY);
        if (!latest.current.drawing || (box[2] - box[0] < MIN_DRAW_DEG && box[3] - box[1] < MIN_DRAW_DEG)) return;
        latest.current.onDraw?.(box);
      };
      m.on("mousedown", begin);
      m.on("touchstart", begin);
      m.on("mousemove", drag);
      m.on("touchmove", drag);
      m.on("mouseup", finish);
      m.on("touchend", finish);

      const popup = new maplibregl.Popup({ className: "pt-popup", maxWidth: "260px" });
      m.on("click", "area-sensors", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        if (!f || latest.current.drawing) return;
        popup.setLngLat((f.geometry as Point).coordinates as [number, number])
          .setHTML(popupHtml(f.properties as unknown as AreaSensorProps, latest.current.area?.summary.sources ?? [])).addTo(m);
      });
      m.on("mouseenter", "area-sensors", () => { if (!latest.current.drawing) m.getCanvas().style.cursor = "pointer"; });
      m.on("mouseleave", "area-sensors", () => { if (!latest.current.drawing) m.getCanvas().style.cursor = ""; });
      setReady(true);
      report();
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  // Draw mode: drags draw instead of panning; Escape cancels.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    if (!drawing) {
      m.dragPan.enable();
      m.boxZoom.enable();
      m.getCanvas().style.cursor = "";
      return;
    }
    m.dragPan.disable();
    m.boxZoom.disable();
    m.getCanvas().style.cursor = "crosshair";
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      (m.getSource("draw-box") as GeoJSONSource).setData(EMPTY);
      latest.current.onDraw?.(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ready, drawing]);

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
    box.setData(boxPolygon(area.bbox));
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
