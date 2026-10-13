export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type CameraKind = "public_road" | "private_lot" | "service_road";

export type CameraProps = {
  kind: "camera";
  camera_id: number;
  osm_id: string | null;
  town: string;
  has_direction: boolean;
  directions_deg: number[] | null;
  direction_ambiguous: boolean;
  alt_directions_deg: number[] | null;
  snap_ambiguous: boolean;
  manufacturer: string | null;
  camera_kind: CameraKind;
  lot_name: string | null;
};

export type PointFeature<P> = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: P;
};

export type CameraCollection = { type: "FeatureCollection"; features: PointFeature<CameraProps>[] };

export type RunSummary = {
  trips: number;
  km: number;
  camera_passes: number;
  captured: number;
  reads: number;
  misreads: number;
  lost_downtime: number;
  lost_missed: number;
  distinct_cameras_read: number;
};

export type RunListItem = {
  id: number;
  created_at: string;
  generator: string;
  weeks: number;
  start_date: string;
  seed: number;
  plate: string;
  plate_state: string;
  summary: RunSummary;
  stale: boolean; // cameras were reloaded after this run was simulated
};

export type Place = { key: string; category: string; lon: number; lat: number; town: string | null; name: string | null };

export type TripProps = {
  id: number;
  seq: number;
  purpose: string;
  origin_key: string;
  dest_key: string;
  dest_category: string;
  planned_depart: string;
  depart: string;
  arrive: string;
  length_m: number;
  duration_s: number;
};

export type TripFeature = {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  properties: TripProps;
};

export type Pass = {
  id: number;
  trip_seq: number;
  pass_seq: number;
  camera_id: number;
  camera_label: string;
  time: string;
  event: "road" | "arrival" | "departure";
  travel_bearing_deg: number | null;
  road_name: string | null;
  captured: boolean;
  match_reason: string;
  noise_outcome: "read" | "missed" | "downtime" | null;
};

export type Read = {
  id: number;
  read_seq: number;
  pass_id: number;
  camera_id: number;
  camera_label: string;
  time: string;
  true_time: string;
  plate_state: string;
  plate: string;
  misread: boolean;
  jitter_s: number;
};

export type GuessPoint = {
  camera_label: string;
  lon: number;
  lat: number;
  support_days: number;
  error_m: number | null;
  is_top_camera: boolean;
  truth: { lon: number; lat: number; name: string | null; category: string | null } | null;
};

export type NaiveGuess = {
  method: string;
  possible: boolean;
  days_used: number;
  top_camera: string | null;
  home: GuessPoint | null;
  work: GuessPoint | null;
};

export type RunDetail = {
  run: RunListItem & {
    match_config: Record<string, string | number>;
    noise_config: Record<string, unknown>;
    anchors: Record<string, Place>;
  };
  naive_guess: NaiveGuess;
  trips: { type: "FeatureCollection"; features: TripFeature[] };
  passes: Pass[];
  reads: Read[];
  outages: { camera_label: string; start_time: string; end_time: string }[];
};

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`);
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

export const getCameras = () => get<CameraCollection>("/cameras");
export const getRuns = () => get<RunListItem[]>("/runs");
export const getRun = (id: number) => get<RunDetail>(`/runs/${id}`);

export type SimulateBody = { template?: string; weeks: number; seed: number; zero_noise?: boolean };

export async function simulate(body: SimulateBody): Promise<{ run_id: number }> {
  const resp = await fetch(`${API_URL}/simulate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`simulate: ${resp.status} ${await resp.text()}`);
  return resp.json();
}
