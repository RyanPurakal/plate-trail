export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** The API's plain-language detail if it sent one. */
async function failure(resp: Response, label: string): Promise<Error> {
  const body = await resp.json().catch(() => null);
  return new Error(typeof body?.detail === "string" ? body.detail : `${label}: ${resp.status}`);
}

export async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`);
  if (!resp.ok) throw await failure(resp, path);
  return resp.json();
}

/** Initial map view from the region file; any field may be null (the map keeps its fallback). */
export type MapDefaults = {
  center: [number, number] | null;
  zoom: number | null;
  bounds: [number, number, number, number] | null; // west, south, east, north
};

export type Region = {
  id: string;
  name: string;
  map: MapDefaults;
};

export const getRegion = () => get<Region>("/region");

export type PointFeature<P> = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: P;
};

/** GET /area: public fixed sensors inside a box. No region file needed. */
export type AreaSensorProps = {
  id: string;
  source: string; // "osm" or a configured file source's name
  directions_deg: number[] | null;
  direction_raw: string | null;
  last_edited: string | null; // OSM edit time; null for file sensors
  also_listed_by?: string[]; // other sources listing the same sensor (shown once); missing from older responses
};

export type AreaSource = {
  id: string;
  name: string;
  license: string | null;
  url: string | null;
  count: number; // sensors this source lists here, including ones shown once under another source
  fetched_at: string | null; // OSM: when the cached response was fetched; file: last-modified time
  latest_edit: string | null;
};

/** Main-road length in the box and how much of it lies near a mapped sensor (distance only). */
export type MainRoads = {
  road_classes: string[];
  within_m: number;
  road_km: number;
  near_sensor_km: number;
  share: number | null; // null when the box has no main roads
};

export type AreaResult = {
  bbox: [number, number, number, number]; // west, south, east, north, snapped to a 0.01 deg grid
  summary: {
    sensor_count: number;
    merged?: number; // listings folded into another source's (same sensor within 15 m); missing from older responses
    with_direction: number;
    area_km2: number;
    sensors_per_100km2: number | null;
    main_roads: MainRoads | null; // null if road data couldn't be loaded
    sources: AreaSource[];
  };
  sensors: { type: "FeatureCollection"; features: PointFeature<AreaSensorProps>[] };
};

/** Fetch an area; errors carry the API's plain-language detail (bad box, busy data source). */
export async function getArea(bbox: [number, number, number, number]): Promise<AreaResult> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/area?bbox=${bbox.join(",")}`);
  } catch {
    throw new Error("Can't reach the Plate Trail API.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `request failed (${resp.status})`;
    throw new Error(detail);
  }
  return resp.json();
}

/** POST /geocode: places matching a town or address, each with a box ready for GET /area. */
export type PlaceMatch = {
  name: string;
  kind: string | null;
  lat: number;
  lon: number;
  bbox: [number, number, number, number];
};

/** Search text goes in the request body and is never stored; only the chosen box reaches the URL. */
export async function searchPlaces(q: string): Promise<{ results: PlaceMatch[]; attribution: string }> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/geocode`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ q }),
    });
  } catch {
    throw new Error("Can't reach the Plate Trail API.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `search failed (${resp.status})`;
    throw new Error(detail);
  }
  return resp.json();
}

/** POST /route/check: one step per sensor the drive passes, in order along the route. */
export type RouteStep = {
  sensor_id: string;
  camera_id: string; // older name for sensor_id
  label: string | null;
  lon: number | null;
  lat: number | null;
  event: string;
  offset_s: number;
  distance_m: number;
  road_name: string | null;
  travel_bearing_deg: number | null;
  read: boolean;
  reason: string;
};

export type RouteLeg = {
  direction: "outbound" | "return";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  length_m: number;
  duration_s: number;
  sensors_passed: number;
  reads: number;
  steps: RouteStep[];
};

export type RouteCheck = {
  network: { kind: "area"; name: string; sensors_mapped?: number };
  legs: RouteLeg[];
  stored: false;
};

/** Start and end go in the request body; the API computes the answer and keeps nothing. */
export async function checkRoute(start: [number, number], end: [number, number]): Promise<RouteCheck> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/route/check`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ start: { lon: start[0], lat: start[1] }, end: { lon: end[0], lat: end[1] } }),
    });
  } catch {
    throw new Error("Can't reach the Plate Trail API.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `check failed (${resp.status})`;
    throw new Error(resp.status === 422 ? `This route can't be checked: ${detail}.` : detail);
  }
  return resp.json();
}

/** POST /route/history: what a read history of one route, driven on a simple schedule, could suggest. */
export type HistoryPlace = {
  lon: number;
  lat: number;
  radius_m: number;
  confidence: string;
  support_days: number;
  possible_days: number;
  what: string;
  nearer_end: "start" | "end";
  distance_m: number;
};

export type HistoryPeriod = {
  days: number;
  trips: number;
  reads: number;
  days_with_reads: number;
  sensors_read: number;
  regular: { sensor_label: string; camera_label: string; time: string; days: number; weekdays: number[] }[];
  places: { overnight?: HistoryPlace; daytime?: HistoryPlace };
  summary: string[];
};

export type RouteHistory = {
  network: RouteCheck["network"];
  schedule: { weekdays: number[]; leave: string; return: string; variation_min: number };
  periods: HistoryPeriod[];
  assumptions: string[];
  stored: false;
};

export type HistorySchedule = { weekdays: number[]; leave: string; return: string };

/** Like checkRoute: the route and schedule go in the request body and nothing is kept. */
export async function routeHistory(start: [number, number], end: [number, number], schedule: HistorySchedule,
  retentionDays?: number[]): Promise<RouteHistory> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/route/history`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        start: { lon: start[0], lat: start[1] }, end: { lon: end[0], lat: end[1] }, ...schedule,
        ...(retentionDays ? { retention_days: retentionDays } : {}),
      }),
    });
  } catch {
    throw new Error("Can't reach the Plate Trail API.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `history failed (${resp.status})`;
    throw new Error(resp.status === 422 ? `This route can't be checked: ${detail}.` : detail);
  }
  return resp.json();
}
