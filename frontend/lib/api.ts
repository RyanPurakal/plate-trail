export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type CameraKind = "public_road" | "private_lot" | "service_road" | "scenario";

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
  extra_cameras: number; // density scenario: synthetic cameras added
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

export type Scenario = {
  extra_cameras: number;
  town: string;
  placement: string;
  cameras: { label: string; lon: number; lat: number; directions_deg: number[] }[];
};

export type EngineAnchor = {
  lon: number;
  lat: number;
  radius_m: number;
  confidence: "high" | "medium" | "low";
  support_days: number;
  possible_days: number;
  nearest_camera: string;
  error_m: number | null;
};

export type Inference = {
  method: string;
  reads_used: number;
  home: EngineAnchor | null;
  work: EngineAnchor | null;
  regular: { camera_label: string; minute_of_day: number; days: number; weekdays: number[] }[];
  anomalies: { time: string; camera_label: string; score: number }[];
  conclusions: string[];
};

export type RunDetail = {
  run: RunListItem & {
    match_config: Record<string, string | number>;
    noise_config: Record<string, unknown>;
    anchors: Record<string, Place>;
    scenario: Scenario | null;
  };
  naive_guess: NaiveGuess;
  inference: Inference;
  stored?: boolean; // false for "your week" results
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

/** Initial map view from the region file; any field may be null (the map keeps its fallback). */
export type MapDefaults = {
  center: [number, number] | null;
  zoom: number | null;
  bounds: [number, number, number, number] | null; // west, south, east, north
};

export type Region = {
  id: string;
  name: string;
  towns: string[];
  student_town: string | null;
  scenario_town: string | null;
  map: MapDefaults;
};

export const getRegion = () => get<Region>("/region");
export const getCameras = () => get<CameraCollection>("/cameras");
export const getRuns = () => get<RunListItem[]>("/runs");
export const getRun = (id: number) => get<RunDetail>(`/runs/${id}`);

export type SimulateBody = {
  generator?: "nhts" | "template";
  template?: string;
  weeks: number;
  seed: number;
  zero_noise?: boolean;
  extra_cameras?: number;
};

export type Job = {
  job_id: string;
  state: "PENDING" | "STARTED" | "PROGRESS" | "SUCCESS" | "FAILURE";
  run_id?: number;
  cached?: boolean;
  error?: string;
  progress?: { stage: string; done: number; total: number };
};

/** Queue a simulation and poll until it finishes; onUpdate receives each status. */
export async function simulateJob(body: SimulateBody, onUpdate: (j: Job) => void): Promise<number> {
  const resp = await fetch(`${API_URL}/jobs/simulate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`simulate: ${resp.status} ${await resp.text()}`);
  let job: Job = await resp.json();
  onUpdate(job);
  while (job.state !== "SUCCESS" && job.state !== "FAILURE") {
    await new Promise((r) => setTimeout(r, 800));
    job = await get<Job>(`/jobs/${job.job_id}`);
    onUpdate(job);
  }
  if (job.state === "FAILURE" || job.run_id == null) throw new Error(job.error ?? "simulation failed");
  return job.run_id;
}

export async function simulate(body: SimulateBody): Promise<{ run_id: number }> {
  const resp = await fetch(`${API_URL}/simulate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`simulate: ${resp.status} ${await resp.text()}`);
  return resp.json();
}
