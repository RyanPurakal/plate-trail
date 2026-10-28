"use client";

import type { Feature, FeatureCollection, Point } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike, Map as MLMap, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { CameraCollection, CameraProps, Inference, MapDefaults, NaiveGuess, Pass, Read, TripFeature } from "@/lib/api";
import { shortTime } from "@/lib/format";

export type Mode = "saw" | "happened";
export type Layers = { routes: boolean; cameras: boolean; skipped: boolean };

type Props = {
  cameras: CameraCollection | null;
  trips: TripFeature[];
  passes: Pass[];
  reads: Read[];
  mode: Mode;
  layers: Layers;
  focusLabel: string | null; // camera to highlight (from the table)
  fitKey: string; // changes when a new run/day is loaded -> refit the view
  guess: NaiveGuess | null; // naive home/work baseline for the whole run
  inference?: Inference | null;
  reveal?: number; // 0 reads only, 1 + inferred anchors, 2 + regular passes, 3 + anomalies
  pickMode?: "home" | "work" | null; // "your week": next map click sets this point
  onPick?: (kind: "home" | "work", lonlat: [number, number]) => void;
  pins?: { home?: [number, number] | null; work?: [number, number] | null };
  initialView?: MapDefaults | null; // region's starting view (GET /region), applied until a run is fitted
  scenarioTown?: string; // where hypothetical cameras are placed (region's scenario_town)
};

/** A geodesic-ish circle polygon (radius in metres) for the inferred anchor areas. */
function circle(lon: number, lat: number, radius: number, n = 64): number[][] {
  const out: number[][] = [];
  const dLat = radius / 110_540;
  const dLon = radius / (111_320 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= n; i++) {
    const a = (2 * Math.PI * i) / n;
    out.push([lon + dLon * Math.sin(a), lat + dLat * Math.cos(a)]);
  }
  return out;
}

const COLORS = {
  public_road: "#e8e2d4",
  private_lot: "#6fa8dc",
  service_road: "#e0a85a",
  scenario: "#b9a2e8",
  read: "#f2a541",
  truth: "#7fd1c7",
  skipped: "#d9534f",
  lost: "#8a8f94",
};

// Used until the region's view arrives, and if the API doesn't send one.
const FALLBACK_VIEW = { center: [-74.39, 40.53] as [number, number], zoom: 11.6 };

const EMPTY = { type: "FeatureCollection" as const, features: [] as Feature[] };

// OpenFreeMap's dark vector style: OpenStreetMap data, no API key.
const BASEMAP = "https://tiles.openfreemap.org/styles/dark";

/** A chevron arrow pointing up (north), drawn at 2x for crisp rendering. One image per camera kind. */
function arrowImage(color: string, size = 48): ImageData {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  g.beginPath();
  g.moveTo(size / 2, 4);
  g.lineTo(size - 10, size - 8);
  g.lineTo(size / 2, size - 18);
  g.lineTo(10, size - 8);
  g.closePath();
  g.lineJoin = "round";
  g.lineWidth = 5;
  g.strokeStyle = "rgba(11,13,14,0.95)";
  g.stroke();
  g.fillStyle = color;
  g.fill();
  return g.getImageData(0, 0, size, size);
}

function cameraFeatures(cameras: CameraCollection | null) {
  const directed: Feature[] = [];
  const undirected: Feature[] = [];
  for (const f of cameras?.features ?? []) {
    const p = f.properties;
    if (p.directions_deg?.length) {
      for (const bearing of p.directions_deg) {
        directed.push({ type: "Feature", geometry: f.geometry, properties: { ...p, bearing, directions_deg: undefined } });
      }
    } else {
      undirected.push({ type: "Feature", geometry: f.geometry, properties: { ...p, directions_deg: undefined } });
    }
  }
  return { directed: { ...EMPTY, features: directed }, undirected: { ...EMPTY, features: undirected } };
}

function cameraIndex(cameras: CameraCollection | null) {
  const m = new Map<string, PointFeature>();
  for (const f of cameras?.features ?? []) if (f.properties.osm_id) m.set(f.properties.osm_id, f);
  return m;
}
type PointFeature = CameraCollection["features"][number];

function readFeatures(reads: Read[], idx: Map<string, PointFeature>) {
  const counts = new Map<string, number>();
  for (const r of reads) counts.set(r.sensor_label, (counts.get(r.sensor_label) ?? 0) + 1);
  const points = [...counts].flatMap(([label, n]) => {
    const f = idx.get(label);
    return f ? [{ type: "Feature" as const, geometry: f.geometry, properties: { label, n } }] : [];
  });
  // The implied trail: reads joined in recorded-time order. It is all an analyst would have.
  const coords = reads.flatMap((r) => (idx.get(r.sensor_label) ? [idx.get(r.sensor_label)!.geometry.coordinates] : []));
  const trail = coords.length > 1 ? [{ type: "Feature" as const, geometry: { type: "LineString" as const, coordinates: coords }, properties: {} }] : [];
  return { points: { ...EMPTY, features: points }, trail: { ...EMPTY, features: trail } };
}

function passFeatures(passes: Pass[], idx: Map<string, PointFeature>) {
  type Agg = { n: number; read: number; lost: number; skipped: number };
  const agg = new Map<string, Agg>();
  for (const p of passes) {
    const a = agg.get(p.sensor_label) ?? { n: 0, read: 0, lost: 0, skipped: 0 };
    a.n += 1;
    if (!p.captured) a.skipped += 1;
    else if (p.noise_outcome === "read") a.read += 1;
    else a.lost += 1;
    agg.set(p.sensor_label, a);
  }
  const features = [...agg].flatMap(([label, a]) => {
    const f = idx.get(label);
    if (!f) return [];
    const status = a.read > 0 ? "read" : a.lost > 0 ? "lost" : "skipped";
    return [{ type: "Feature" as const, geometry: f.geometry, properties: { label, ...a, status } }];
  });
  return { ...EMPTY, features };
}

function popupHtml(p: CameraProps & { bearing?: number }, passes: Pass[], reads: Read[], scenarioTown: string) {
  const label = p.osm_id ?? `camera ${p.sensor_id}`;
  const mine = passes.filter((x) => x.sensor_label === label);
  const rd = reads.filter((x) => x.sensor_label === label);
  const kind = { public_road: "public road", private_lot: "private lot", service_road: "service street",
    scenario: `hypothetical camera (simulated placement on an arterial in ${scenarioTown})` }[p.camera_kind];
  const facing = p.has_direction ? `faces ${(p.directions_deg ?? [p.bearing]).join(" / ")}°` : "no direction tag";
  const flags = [p.snap_ambiguous && "snap ambiguous", p.direction_ambiguous && "direction ambiguous"].filter(Boolean);
  const lines = [
    `<div class="pop-title">${label}</div>`,
    `<div>${kind}${p.lot_name ? ` · ${p.lot_name}` : ""} · ${facing}</div>`,
    p.manufacturer ? `<div class="pop-dim">${p.manufacturer}</div>` : "",
    flags.length ? `<div class="pop-warn">${flags.join(" · ")}</div>` : "",
    mine.length || rd.length
      ? `<div class="pop-sep">${rd.length} read${rd.length === 1 ? "" : "s"} · ${mine.length} pass${mine.length === 1 ? "" : "es"}</div>`
      : "",
    ...rd.slice(0, 4).map((r) => `<div class="pop-row">${shortTime(r.time)} · ${r.plate_state} ${r.plate}</div>`),
  ];
  return lines.join("");
}

function markerEl(text: string, cls: string, title: string) {
  const el = document.createElement("div");
  el.className = `pt-marker ${cls}`;
  el.textContent = text;
  el.title = title;
  return el;
}

export default function MapView({ cameras, trips, passes, reads, mode, layers, focusLabel, fitKey, guess,
  inference = null, reveal = 0, pickMode = null, onPick, pins, initialView = null, scenarioTown = "the study area" }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const latest = useRef({ cameras, passes, reads, scenarioTown });
  latest.current = { cameras, passes, reads, scenarioTown };
  const pickRef = useRef({ mode: pickMode, onPick });
  pickRef.current = { mode: pickMode, onPick };

  // Create the map once.
  useEffect(() => {
    if (!el.current) return;
    // Served from public/ (copied by scripts/copy-maplibre-worker.mjs); the bundled
    // default path doesn't survive Next.js bundling.
    maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");
    const m = new maplibregl.Map({
      container: el.current,
      style: BASEMAP,
      center: FALLBACK_VIEW.center,
      zoom: FALLBACK_VIEW.zoom,
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");
    m.on("load", () => {
      for (const kind of ["public_road", "private_lot", "service_road", "scenario"] as const) {
        m.addImage(`arrow-${kind}`, arrowImage(COLORS[kind]), { pixelRatio: 2 });
      }
      for (const id of ["routes", "trail", "reads", "passes", "cam-dir", "cam-undir", "focus", "guess-err",
        "eng-area", "eng-err", "regular", "anom"]) {
        m.addSource(id, { type: "geojson", data: EMPTY });
      }
      m.addLayer({
        id: "routes-glow", type: "line", source: "routes",
        paint: { "line-color": COLORS.truth, "line-width": 7, "line-opacity": 0.12, "line-blur": 4 },
        layout: { "line-join": "round", "line-cap": "round" },
      });
      m.addLayer({
        id: "routes", type: "line", source: "routes",
        paint: { "line-color": COLORS.truth, "line-width": 1.6, "line-opacity": 0.75 },
        layout: { "line-join": "round", "line-cap": "round" },
      });
      m.addLayer({
        id: "trail", type: "line", source: "trail",
        paint: { "line-color": COLORS.read, "line-width": 1.4, "line-dasharray": [2, 3], "line-opacity": 0.75 },
      });
      m.addLayer({
        id: "cam-undir", type: "circle", source: "cam-undir",
        paint: { "circle-radius": 4, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": COLORS.public_road, "circle-stroke-width": 1.5 },
      });
      m.addLayer({
        id: "cam-dir", type: "symbol", source: "cam-dir",
        layout: {
          "icon-image": ["concat", "arrow-", ["get", "camera_kind"]],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 10, 0.6, 15, 1.1],
          "icon-rotate": ["get", "bearing"], "icon-rotation-alignment": "map", "icon-allow-overlap": true,
        },
        paint: { "icon-opacity": 0.92 },
      });
      m.addLayer({
        id: "passes", type: "circle", source: "passes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "n"], 1, 9, 20, 20],
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-width": 2,
          "circle-stroke-color": ["match", ["get", "status"], "read", COLORS.read, "lost", COLORS.lost, COLORS.skipped],
        },
      });
      m.addLayer({
        id: "reads-halo", type: "circle", source: "reads",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "n"], 1, 16, 20, 34],
          "circle-color": COLORS.read, "circle-opacity": 0.18, "circle-blur": 0.9,
        },
      });
      m.addLayer({
        id: "reads", type: "circle", source: "reads",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "n"], 1, 5, 20, 12],
          "circle-color": COLORS.read, "circle-stroke-color": "#1a1206", "circle-stroke-width": 1.5,
        },
      });
      m.addLayer({
        id: "eng-area", type: "fill", source: "eng-area",
        paint: { "fill-color": ["match", ["get", "kind"], "home", COLORS.read, "#c7b8f5"], "fill-opacity": 0.1 },
      });
      m.addLayer({
        id: "eng-area-line", type: "line", source: "eng-area",
        paint: { "line-color": ["match", ["get", "kind"], "home", COLORS.read, "#c7b8f5"], "line-width": 1.5,
          "line-dasharray": [3, 2] },
      });
      m.addLayer({
        id: "eng-err", type: "line", source: "eng-err",
        paint: { "line-color": "#c7b8f5", "line-width": 1.2, "line-dasharray": [1, 2], "line-opacity": 0.8 },
      });
      m.addLayer({
        id: "regular", type: "circle", source: "regular",
        paint: { "circle-radius": 14, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#c7b8f5",
          "circle-stroke-width": 2, "circle-stroke-opacity": 0.9 },
      });
      m.addLayer({
        id: "anom", type: "circle", source: "anom",
        paint: { "circle-radius": 7, "circle-color": COLORS.skipped, "circle-stroke-color": "#1a0b0b", "circle-stroke-width": 1.5 },
      });
      m.addLayer({
        id: "guess-err", type: "line", source: "guess-err",
        paint: { "line-color": "#ffffff", "line-width": 1.2, "line-dasharray": [1, 2], "line-opacity": 0.7 },
      });
      m.addLayer({
        id: "focus", type: "circle", source: "focus",
        paint: { "circle-radius": 22, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 },
      });

      const popup = new maplibregl.Popup({ closeButton: false, className: "pt-popup", maxWidth: "280px" });
      for (const layer of ["cam-dir", "cam-undir"]) {
        m.on("mouseenter", layer, (e: MapLayerMouseEvent) => {
          m.getCanvas().style.cursor = "crosshair";
          const f = e.features?.[0];
          if (!f) return;
          const { passes: ps, reads: rs, scenarioTown: town } = latest.current;
          popup.setLngLat((f.geometry as Point).coordinates as [number, number])
            .setHTML(popupHtml(f.properties as unknown as CameraProps & { bearing?: number }, ps, rs, town)).addTo(m);
        });
        m.on("mouseleave", layer, () => {
          m.getCanvas().style.cursor = "";
          popup.remove();
        });
      }
      setReady(true);
    });
    m.on("click", (e) => {
      const p = pickRef.current;
      if (p.mode && p.onPick) p.onPick(p.mode, [e.lngLat.lng, e.lngLat.lat]);
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  const set = (id: string, data: FeatureCollection) => (map.current?.getSource(id) as GeoJSONSource | undefined)?.setData(data);

  // Cameras.
  useEffect(() => {
    if (!ready) return;
    const { directed, undirected } = cameraFeatures(cameras);
    set("cam-dir", directed);
    set("cam-undir", undirected);
  }, [ready, cameras]);

  // Run data, depending on mode.
  useEffect(() => {
    if (!ready) return;
    const idx = cameraIndex(cameras);
    const saw = mode === "saw";
    const r = readFeatures(reads, idx);
    set("reads", saw ? r.points : EMPTY);
    set("trail", saw ? r.trail : EMPTY);
    set("routes", !saw && layers.routes ? { ...EMPTY, features: trips as unknown as Feature[] } : EMPTY);
    const visiblePasses = layers.skipped ? passes : passes.filter((p) => p.captured);
    set("passes", saw ? EMPTY : passFeatures(visiblePasses, idx));
    for (const id of ["cam-dir", "cam-undir"]) {
      map.current!.setLayoutProperty(id, "visibility", layers.cameras ? "visible" : "none");
    }
  }, [ready, cameras, trips, passes, reads, mode, layers]);

  // Naive home/work guess markers; in HAPPENED mode also the true anchors and the error lines.
  const markers = useRef<maplibregl.Marker[]>([]);
  useEffect(() => {
    if (!ready) return;
    markers.current.forEach((mk) => mk.remove());
    markers.current = [];
    const lines: Feature[] = [];
    const same = guess?.home && guess?.work && guess.home.sensor_label === guess.work.sensor_label;
    for (const [kind, g] of [["home", guess?.home], ["work", guess?.work]] as const) {
      if (!g) continue;
      const word = kind === "home" ? "HOME" : "WORK";
      // When both guesses are the same camera, one combined marker (drawn once, with the home pass).
      if (!(same && kind === "work")) {
        markers.current.push(new maplibregl.Marker({
          element: markerEl(same ? "HOME? · WORK?" : `${word}?`, `guess guess-${kind}`,
            `Naive guess (${same ? "home and work" : kind}): camera ${g.sensor_label}`),
          anchor: "bottom", offset: [0, -10],
        }).setLngLat([g.lon, g.lat]).addTo(map.current!));
      }
      if (mode === "happened" && g.truth) {
        markers.current.push(new maplibregl.Marker({ element: markerEl(word, `truth truth-${kind}`,
          `True ${kind}${g.truth.name ? `: ${g.truth.name}` : ""}`), anchor: "top", offset: [0, 8] })
          .setLngLat([g.truth.lon, g.truth.lat]).addTo(map.current!));
        lines.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[g.lon, g.lat], [g.truth.lon, g.truth.lat]] } });
      }
    }
    set("guess-err", { ...EMPTY, features: lines });
  }, [ready, guess, mode]);

  // Inference engine layers, revealed step by step.
  const engMarkers = useRef<maplibregl.Marker[]>([]);
  useEffect(() => {
    if (!ready) return;
    engMarkers.current.forEach((mk) => mk.remove());
    engMarkers.current = [];
    const areas: Feature[] = [];
    const errs: Feature[] = [];
    if (inference && reveal >= 1) {
      for (const [kind, a, truth] of [["home", inference.home, guess?.home?.truth], ["work", inference.work, guess?.work?.truth]] as const) {
        if (!a) continue;
        areas.push({ type: "Feature", properties: { kind }, geometry: { type: "Polygon", coordinates: [circle(a.lon, a.lat, a.radius_m)] } });
        engMarkers.current.push(new maplibregl.Marker({
          element: markerEl(`${kind === "home" ? "HOME" : "WORK"} ~ ${a.confidence}`, `engine engine-${kind}`,
            `Inference engine: ${kind} within ~${(a.radius_m / 1000).toFixed(1)} km (${a.support_days}/${a.possible_days} days)`),
          anchor: "left", offset: [10, 0],
        }).setLngLat([a.lon, a.lat]).addTo(map.current!));
        if (mode === "happened" && truth) {
          errs.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[a.lon, a.lat], [truth.lon, truth.lat]] } });
        }
      }
    }
    set("eng-area", { ...EMPTY, features: areas });
    set("eng-err", { ...EMPTY, features: errs });
    const idx = cameraIndex(cameras);
    const regular = inference && reveal >= 2
      ? [...new Set(inference.regular.map((r) => r.sensor_label))].flatMap((l) => (idx.get(l) ? [{ type: "Feature" as const, geometry: idx.get(l)!.geometry, properties: {} }] : []))
      : [];
    set("regular", { ...EMPTY, features: regular });
    const anom = inference && reveal >= 3
      ? inference.anomalies.flatMap((a) => (idx.get(a.sensor_label) ? [{ type: "Feature" as const, geometry: idx.get(a.sensor_label)!.geometry, properties: {} }] : []))
      : [];
    set("anom", { ...EMPTY, features: anom });
  }, [ready, inference, reveal, mode, cameras, guess]);

  // "Your week" pins and pick cursor.
  const pinMarkers = useRef<maplibregl.Marker[]>([]);
  useEffect(() => {
    if (!ready) return;
    pinMarkers.current.forEach((mk) => mk.remove());
    pinMarkers.current = [];
    for (const [kind, pt] of [["home", pins?.home], ["work", pins?.work]] as const) {
      if (!pt) continue;
      pinMarkers.current.push(new maplibregl.Marker({ element: markerEl(kind === "home" ? "YOUR HOME" : "YOUR WORK", "truth", "") , anchor: "top", offset: [0, 8] })
        .setLngLat(pt).addTo(map.current!));
    }
    map.current!.getCanvas().style.cursor = pickMode ? "crosshair" : "";
  }, [ready, pins, pickMode]);

  // Highlight a camera picked in the table.
  useEffect(() => {
    if (!ready) return;
    const f = focusLabel ? cameraIndex(cameras).get(focusLabel) : undefined;
    set("focus", f ? { ...EMPTY, features: [{ type: "Feature", geometry: f.geometry, properties: {} }] } : EMPTY);
    if (f) map.current!.easeTo({ center: f.geometry.coordinates, zoom: Math.max(map.current!.getZoom(), 14), duration: 700 });
  }, [ready, focusLabel, cameras]);

  // Move to the region's starting view once, unless a run has already been fitted.
  const viewApplied = useRef(false);
  useEffect(() => {
    if (!ready || !initialView || viewApplied.current) return;
    viewApplied.current = true;
    if (fitKey) return;
    const { bounds, center, zoom } = initialView;
    if (bounds) map.current!.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: 40, duration: 0 });
    else if (center && zoom != null) map.current!.jumpTo({ center, zoom });
    // fitKey intentionally omitted: it is only checked at the moment the view arrives
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, initialView]);

  // Fit to the run when it (or the day filter) changes.
  useEffect(() => {
    if (!ready || !fitKey) return;
    const pts: [number, number][] = [];
    for (const t of trips) pts.push(...t.geometry.coordinates);
    if (!pts.length) return;
    const lons = pts.map((p) => p[0]);
    const lats = pts.map((p) => p[1]);
    const bounds: LngLatBoundsLike = [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
    map.current!.fitBounds(bounds, { padding: { top: 60, bottom: 60, left: 60, right: 60 }, duration: 900, maxZoom: 14 });
    // trips intentionally omitted: refit only when the selection changes, not on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, fitKey]);

  return <div ref={el} className="map" />;
}
