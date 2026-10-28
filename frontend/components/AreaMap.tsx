"use client";

import type { Feature } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLat, Map as MLMap, MapLayerMouseEvent, MapMouseEvent, MapTouchEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { AreaResult, MapDefaults, RouteLeg } from "@/lib/api";
import { cornersToBBox, type BBox } from "@/lib/area";
import type { Pt } from "@/lib/routes";

type Props = {
  area: AreaResult | null;
  initialView?: MapDefaults | null; // region's starting view, used until an area is loaded
  onView: (bounds: BBox) => void; // current visible box, reported after each move
  drawing?: boolean; // drag on the map draws a box instead of panning
  onDraw?: (box: BBox | null) => void; // drawn box, or null when drawing is cancelled
  selectedId?: string | null; // sensor shown in the sidebar's detail card
  onSelect?: (id: string) => void; // a sensor was clicked
  placing?: boolean; // clicks place a route point instead of selecting sensors
  onPlace?: (pt: Pt | null) => void; // placed point, or null when placing is cancelled
  routeMarks?: { start: Pt | null; end: Pt | null } | null; // route being added or shown
  routeLegs?: RouteLeg[] | null; // checked route by road, replacing the straight line
  stepFocus?: { at: Pt; cameraId: string } | null; // route timeline step picked in the sidebar
};

const FALLBACK_VIEW = { center: [-74.39, 40.53] as [number, number], zoom: 11.6 };
const BASEMAP = "https://tiles.openfreemap.org/styles/dark";
const EMPTY = { type: "FeatureCollection" as const, features: [] as Feature[] };
const MIN_DRAW_DEG = 0.002; // smaller drags (about 200 m) are treated as clicks, not boxes

const boxPolygon = ([w, s, e, n]: BBox): Feature => ({
  type: "Feature", properties: {},
  geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
});

/** Map for the Explore view: the explored box and the public sensors inside it. */
export default function AreaMap({ area, initialView = null, onView, drawing = false, onDraw, selectedId = null, onSelect, placing = false, onPlace, routeMarks = null, routeLegs = null, stepFocus = null }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const latest = useRef({ area, onView, drawing, onDraw, onSelect, placing, onPlace });
  latest.current = { area, onView, drawing, onDraw, onSelect, placing, onPlace };

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
      m.addLayer({
        id: "area-sensor-selected", type: "circle", source: "area-sensors", filter: ["==", ["get", "id"], ""],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 8, 15, 13],
          "circle-color": "transparent",
          "circle-stroke-color": "#e8e2d4",
          "circle-stroke-width": 2,
        },
      });
      m.addSource("route-drive", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "route-drive", type: "line", source: "route-drive", filter: ["==", ["geometry-type"], "LineString"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#7fd1c7",
          "line-width": ["case", ["==", ["get", "direction"], "outbound"], 3, 2],
          "line-opacity": ["case", ["==", ["get", "direction"], "outbound"], 0.9, 0.35],
        },
      });
      m.addLayer({
        id: "route-passes", type: "circle", source: "route-drive", filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 7, 15, 12],
          "circle-color": "transparent",
          "circle-stroke-color": ["case", ["get", "read"], "#f2a541", "#8a8f94"],
          "circle-stroke-width": 2,
        },
      });
      m.addLayer({
        id: "route-step-focus", type: "circle", source: "route-drive",
        filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "id"], ""]],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 11, 15, 17],
          "circle-color": "transparent",
          "circle-stroke-color": "#e8e2d4",
          "circle-stroke-width": 2.5,
        },
      });
      m.addSource("route-marks", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "route-line", type: "line", source: "route-marks", filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#e8e2d4", "line-width": 1.5, "line-dasharray": [1, 2], "line-opacity": 0.8 },
      });
      m.addLayer({
        id: "route-points", type: "circle", source: "route-marks", filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 6,
          "circle-color": ["case", ["==", ["get", "end"], "start"], "#e8e2d4", "#0b0d0e"],
          "circle-stroke-color": "#e8e2d4",
          "circle-stroke-width": 2,
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

      const busy = () => latest.current.drawing || latest.current.placing;
      m.on("click", (e: MapMouseEvent) => {
        if (latest.current.placing) latest.current.onPlace?.(e.lngLat.toArray() as Pt);
      });
      m.on("click", "area-sensors", (e: MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.id;
        if (typeof id === "string" && !busy()) latest.current.onSelect?.(id);
      });
      m.on("mouseenter", "area-sensors", () => { if (!busy()) m.getCanvas().style.cursor = "pointer"; });
      m.on("mouseleave", "area-sensors", () => { if (!busy()) m.getCanvas().style.cursor = ""; });
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

  // Placing route points: crosshair cursor; Escape cancels.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !placing) return;
    m.getCanvas().style.cursor = "crosshair";
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") latest.current.onPlace?.(null); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      m.getCanvas().style.cursor = "";
    };
  }, [ready, placing]);

  // Start/end points of the route being added or shown, joined by a straight dotted line.
  const start = routeMarks?.start ?? null;
  const end = routeMarks?.end ?? null;
  const marksKey = JSON.stringify([start, end]);
  useEffect(() => {
    if (!ready) return;
    const m = map.current!;
    const pts = [start, end].filter((p): p is Pt => !!p);
    const features: Feature[] = pts.map((p, i) => ({
      type: "Feature", properties: { end: i === 0 ? "start" : "end" }, geometry: { type: "Point", coordinates: p },
    }));
    if (pts.length === 2 && !routeLegs) features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts } });
    (m.getSource("route-marks") as GeoJSONSource).setData({ ...EMPTY, features });
    if (pts.length === 2 && !routeLegs && !pts.every((p) => m.getBounds().contains(p))) {
      const b = cornersToBBox(pts[0], pts[1]);
      m.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 80, maxZoom: 14, duration: 600 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, marksKey, routeLegs]);

  // Checked route: the drive there (solid) and back (fainter), and each sensor it passes,
  // ringed amber if it would record the trip one way or the other, grey if not.
  useEffect(() => {
    if (!ready) return;
    const m = map.current!;
    const features: Feature[] = [];
    const read = new Map<string, { at: Pt; read: boolean }>();
    for (const leg of routeLegs ?? []) {
      features.push({ type: "Feature", properties: { direction: leg.direction }, geometry: leg.geometry });
      for (const st of leg.steps) {
        if (st.lon == null || st.lat == null) continue;
        const prev = read.get(st.sensor_id);
        read.set(st.sensor_id, { at: [st.lon, st.lat], read: !!prev?.read || st.read });
      }
    }
    for (const [id, p] of read) {
      features.push({ type: "Feature", properties: { id, read: p.read }, geometry: { type: "Point", coordinates: p.at } });
    }
    (m.getSource("route-drive") as GeoJSONSource).setData({ ...EMPTY, features });
    const coords = (routeLegs ?? []).flatMap((l) => l.geometry.coordinates);
    if (!coords.length) return;
    const lons = coords.map((c) => c[0]);
    const lats = coords.map((c) => c[1]);
    const b: BBox = [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
    m.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 80, maxZoom: 15, duration: 600 });
  }, [ready, routeLegs]);

  // Timeline step picked in the sidebar: ring its sensor and bring it into view, closer in if zoomed out.
  const focusKey = JSON.stringify(stepFocus);
  useEffect(() => {
    if (!ready) return;
    const m = map.current!;
    m.setFilter("route-step-focus", ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "id"], stepFocus?.cameraId ?? ""]]);
    if (!stepFocus) return;
    if (m.getZoom() < 14 || !m.getBounds().contains(stepFocus.at)) {
      m.easeTo({ center: stepFocus.at, zoom: Math.max(m.getZoom(), 14), duration: 500 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focusKey]);

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

  // Ring the selected sensor; bring it into view if it is off screen (e.g. picked with Previous/Next).
  useEffect(() => {
    if (!ready) return;
    const m = map.current!;
    m.setFilter("area-sensor-selected", ["==", ["get", "id"], selectedId ?? ""]);
    const f = selectedId ? area?.sensors.features.find((x) => x.properties.id === selectedId) : null;
    if (!f) return;
    const at = f.geometry.coordinates as [number, number];
    if (!m.getBounds().contains(at)) m.easeTo({ center: at, duration: 400 });
  }, [ready, area, selectedId]);

  return <div ref={el} className="map" role="region" aria-label="Map of the explored area" />;
}
