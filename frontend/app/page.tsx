"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import ExploreView from "@/components/ExploreView";
import MyAreas from "@/components/MyAreas";
import CompareAreas from "@/components/CompareAreas";
import CompareRoutes from "@/components/CompareRoutes";
import SinceLastVisit from "@/components/SinceLastVisit";
import MyRoutes, { type RouteCheckState, type RouteDraft, type StepFocus } from "@/components/MyRoutes";
import type { Layers, Mode } from "@/components/MapView";
import {
  checkRoute,
  FALLBACK_REGION_NAME,
  FALLBACK_SCENARIO_TOWN,
  getArea,
  getCameras,
  getRegion,
  getRun,
  getRuns,
  simulateJob,
  type AreaResult,
  type CameraCollection,
  type Job,
  type Inference,
  type NaiveGuess,
  type Region,
  type RunDetail,
  type RunListItem,
} from "@/lib/api";
import { formatBBox, parseBBox, viewToBBox, type BBox } from "@/lib/area";
import { dayKey, km, parts, templateName } from "@/lib/format";
import { areaKey, areaSnapshot, forgetLooks, makeSnapshot, recordLook, routeKey, type SnapshotChange } from "@/lib/snapshots";
import { addArea, AREAS_KEY, loadAreas, removeArea, renameArea, saveAreas, type SavedArea } from "@/lib/areas";
import { addRoute, loadRoutes, removeRoute, renameRoute, saveRoutes, STORAGE_KEY, type Pt, type SavedRoute } from "@/lib/routes";
import { onTabListKeyDown, tabStop } from "@/lib/tabs";
import { areaAnnouncement, nextAnnouncement, routeAnnouncement } from "@/lib/announce";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });
const AreaMap = dynamic(() => import("@/components/AreaMap"), { ssr: false });
// Example study views load only when a study tab is opened, so the check-up stays light.
const LogTable = dynamic(() => import("@/components/LogTable"));
const PopulationView = dynamic(() => import("@/components/PopulationView"));
const YourWeek = dynamic(() => import("@/components/YourWeek"));

type Tab = "explore" | "driver" | "population" | "yourweek";
type StudyTab = Exclude<Tab, "explore">;

const STUDY_TABS: readonly (readonly [StudyTab, string])[] = [
  ["driver", "One driver"], ["population", "Population & policy"], ["yourweek", "Your week"],
];
const isStudyTab = (s: string | null): s is StudyTab => STUDY_TABS.some(([k]) => k === s);

/** Keep the explored box or the example-study section (and nothing else) in the address bar so the page can be shared. */
function setPageUrl(tab: Tab, bbox: BBox | null) {
  const q = tab !== "explore" ? `?study=${tab}` : bbox ? `?bbox=${formatBBox(bbox)}` : "";
  window.history.replaceState(null, "", window.location.pathname + q);
}

const REVEAL_STEPS = ["Reads", "Places", "Schedule", "Anomalies"];

function RevealCard({ inference, reveal, setReveal, mode }: {
  inference: Inference; reveal: number; setReveal: (n: number) => void; mode: Mode;
}) {
  const err = (a: Inference["home"]) => (a && a.error_m != null && mode === "happened"
    ? ` · off by ${(a.error_m / 1000).toFixed(a.error_m < 10000 ? 2 : 1)} km` : "");
  return (
    <section className="naive reveal">
      <div className="nb-head">
        <span>What an analyst can infer</span>
        <span className="nb-badge engine-badge" title={inference.method}>inference engine</span>
      </div>
      <div className="steps" role="tablist" aria-label="reveal step" onKeyDown={onTabListKeyDown}>
        {REVEAL_STEPS.map((label, i) => (
          <button key={label} role="tab" aria-selected={reveal === i} tabIndex={tabStop(reveal === i)} className={reveal >= i ? "on" : ""} onClick={() => setReveal(i)}>
            <span>{i + 1}</span>{label}
          </button>
        ))}
      </div>
      {reveal === 0 && <div className="nb-note">Step through what the read log alone supports. Each step adds a layer to the map.</div>}
      {reveal >= 1 && (
        <>
          {inference.home ? (
            <div className="nb-row"><span className="nb-k eng">Home</span>
              <span>within ~{(inference.home.radius_m / 1000).toFixed(1)} km · {inference.home.confidence} ({inference.home.support_days}/{inference.home.possible_days} nights){err(inference.home)}</span><span /></div>
          ) : <div className="nb-note">Not enough overnight gaps to place a home.</div>}
          {inference.work ? (
            <div className="nb-row"><span className="nb-k eng">Work</span>
              <span>within ~{(inference.work.radius_m / 1000).toFixed(1)} km · {inference.work.confidence} ({inference.work.support_days}/{inference.work.possible_days} weekdays){err(inference.work)}</span><span /></div>
          ) : <div className="nb-note">No long weekday stay bracketed by reads, so no work estimate.</div>}
        </>
      )}
      {reveal >= 2 && (
        <div className="nb-note">{inference.regular.length} regular pass{inference.regular.length === 1 ? "" : "es"} (same camera, same time of day, 3+ days) ringed on the map.</div>
      )}
      {reveal >= 3 && (
        <div className="nb-note">{inference.anomalies.length} out-of-routine read{inference.anomalies.length === 1 ? "" : "s"} marked in red.</div>
      )}
      {reveal >= 1 && (
        <ul className="conclusions">
          {inference.conclusions.slice(0, reveal >= 3 ? 8 : reveal >= 2 ? 7 : 2).map((c) => <li key={c}>{c}</li>)}
        </ul>
      )}
      <div className="nb-note">Confidence reflects how consistent the evidence is, not how close the estimate is: cameras are rarely next to a home.</div>
    </section>
  );
}

function jobLabel(job: Job | null): string {
  if (!job) return "queued…";
  if (job.state === "PROGRESS" && job.progress) {
    const { stage, done, total } = job.progress;
    return total > 1 ? `${stage} ${done}/${total}` : `${stage}…`;
  }
  const labels: Record<Job["state"], string> = {
    PENDING: "queued…", STARTED: "loading…", PROGRESS: "running…", SUCCESS: "done", FAILURE: "failed",
  };
  return labels[job.state];
}

function NaiveCard({ guess, mode }: { guess: NaiveGuess; mode: Mode }) {
  const row = (label: string, g: NaiveGuess["home"]) =>
    g ? (
      <div className="nb-row">
        <span className="nb-k">{label}?</span>
        <span>
          camera {g.camera_label.replace("node/", "")} <span className="dim">· {g.support_days} day{g.support_days === 1 ? "" : "s"}</span>
          {g.is_top_camera && <span className="dim"> · = top camera</span>}
        </span>
        <span className={`nb-err ${mode}`}>
          {g.error_m == null ? "no truth" : `off by ${(g.error_m / 1000).toFixed(g.error_m < 10000 ? 2 : 1)} km`}
        </span>
      </div>
    ) : null;
  return (
    <section className="naive">
      <div className="nb-head">
        <span>Naive home / work guess</span>
        <span className="nb-badge" title={guess.method}>baseline · not the inference engine</span>
      </div>
      {guess.possible ? (
        <>
          {row("Home", guess.home)}
          {row("Work", guess.work)}
          <div className="nb-note">
            From {guess.days_used} days of reads: home = camera of the day&apos;s first/last read, work = camera before
            the day&apos;s longest gap. Errors are against ground truth.
          </div>
        </>
      ) : (
        <div className="nb-note">No guess possible: fewer than 2 days with 2+ reads ({guess.days_used} usable).</div>
      )}
    </section>
  );
}

export default function Home() {
  const [cameras, setCameras] = useState<CameraCollection | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [mode, setMode] = useState<Mode>("saw");
  const [layers, setLayers] = useState<Layers>({ routes: true, cameras: true, skipped: true });
  const [day, setDay] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState<Tab>("explore");
  const [reveal, setReveal] = useState(0);
  const [pickMode, setPickMode] = useState<"home" | "work" | null>(null);
  const [pins, setPins] = useState<{ home: [number, number] | null; work: [number, number] | null }>({ home: null, work: null });
  const [region, setRegion] = useState<Region | null>(null);
  const [form, setForm] = useState({ generator: "nhts" as "nhts" | "template", template: "", weeks: 1, seed: 1, extra: 0, town: "" });
  const [area, setArea] = useState<AreaResult | null>(null);
  const [areaLoading, setAreaLoading] = useState(false);
  const [areaError, setAreaError] = useState<string | null>(null);
  const [areaShrunk, setAreaShrunk] = useState(false);
  const [areaChange, setAreaChange] = useState<SnapshotChange | null>(null); // vs this browser's last look at the box
  const [drawing, setDrawing] = useState(false);
  const [sensorId, setSensorId] = useState<string | null>(null);
  const [savedAreas, setSavedAreas] = useState<SavedArea[]>([]);
  const [areasSaved, setAreasSaved] = useState(true);
  const [routes, setRoutes] = useState<SavedRoute[]>([]);
  const [routesSaved, setRoutesSaved] = useState(true);
  const [routeDraft, setRouteDraft] = useState<RouteDraft | null>(null);
  const [shownRoute, setShownRoute] = useState<string | null>(null);
  const [routeChecks, setRouteChecks] = useState<Record<string, RouteCheckState>>({}); // by route id, this page only
  const [stepFocus, setStepFocus] = useState<StepFocus | null>(null); // timeline step shown on the map
  const [announcement, setAnnouncement] = useState(""); // read by screen readers when an area loads or a route is checked
  const announce = (text: string) => setAnnouncement((prev) => nextAnnouncement(prev, text));
  const viewBox = useRef<BBox | null>(null);

  async function loadArea(bbox: BBox) {
    setAreaLoading(true);
    setAreaError(null);
    announce("Loading public map data for this area…");
    try {
      const a = await getArea(bbox);
      setArea(a);
      // Saved areas' looks are kept however long ago they were; read fresh so another tab's saves count too.
      const pinned = new Set(loadAreas().map((x) => areaKey(x.bbox)));
      const change = recordLook(areaKey(a.bbox), areaSnapshot(a), pinned);
      setAreaChange(change);
      announce(areaAnnouncement(a, change));
      setSensorId(null);
      setPageUrl("explore", a.bbox);
    } catch (e) {
      setAreaError((e as Error).message);
    } finally {
      setAreaLoading(false);
    }
  }

  function exploreView() {
    if (!viewBox.current) return;
    const { bbox, shrunk } = viewToBBox(viewBox.current);
    setAreaShrunk(shrunk);
    loadArea(bbox);
  }

  function exploreDrawn(box: BBox | null) {
    setDrawing(false);
    if (!box) return;
    const { bbox, shrunk } = viewToBBox(box);
    setAreaShrunk(shrunk);
    loadArea(bbox);
  }

  // Saved routes and areas live only in this browser; follow edits made in other tabs too.
  useEffect(() => {
    setRoutes(loadRoutes());
    setSavedAreas(loadAreas());
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setRoutes(loadRoutes());
      if (e.key === AREAS_KEY) setSavedAreas(loadAreas());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  function updateAreas(next: SavedArea[]) {
    setSavedAreas(next);
    setAreasSaved(saveAreas(next));
  }

  function updateRoutes(next: SavedRoute[]) {
    setRoutes(next);
    setRoutesSaved(saveRoutes(next));
    if (shownRoute && !next.some((r) => r.id === shownRoute)) setShownRoute(null);
    setRouteChecks((c) => Object.fromEntries(Object.entries(c).filter(([id]) => next.some((r) => r.id === id))));
    forgetLooks((k) => k.startsWith("route:") && !next.some((r) => routeKey(r.id) === k));
  }

  // Results stay in page memory only; reloading the page or deleting the route drops them.
  async function runRouteCheck(id: string) {
    const r = routes.find((x) => x.id === id);
    if (!r) return;
    setRouteChecks((c) => ({ ...c, [id]: { loading: true, result: null, error: null } }));
    announce(`Checking ${r.name}…`);
    try {
      const result = await checkRoute(r.start, r.end);
      const change = recordLook(routeKey(id), makeSnapshot(result.legs.flatMap((l) => l.steps.map((st) => st.camera_id))));
      setRouteChecks((c) => ({ ...c, [id]: { loading: false, result, error: null, change } }));
      announce(routeAnnouncement(r.name, result, change));
    } catch (e) {
      setRouteChecks((c) => ({ ...c, [id]: { loading: false, result: null, error: (e as Error).message } }));
    }
  }

  function placeRoutePoint(pt: Pt | null) {
    if (!pt) return setRouteDraft(null);
    setRouteDraft((d) => (!d ? d : !d.start ? { start: pt, end: null } : !d.end ? { ...d, end: pt } : d));
  }

  function saveDraft(name: string) {
    if (!routeDraft?.start || !routeDraft.end) return;
    const next = addRoute(routes, name, routeDraft.start, routeDraft.end);
    updateRoutes(next);
    setRouteDraft(null);
    setShownRoute(next[next.length - 1]?.id ?? null);
  }

  const shown = routes.find((r) => r.id === shownRoute);
  const routeMarks = routeDraft ?? (shown ? { start: shown.start, end: shown.end } : null);
  const routeLegs = !routeDraft && shown ? routeChecks[shown.id]?.result?.legs ?? null : null;
  useEffect(() => setStepFocus(null), [routeLegs]);

  useEffect(() => {
    // Explore is the home page; an area link (?bbox=w,s,e,n) loads that area, ?study=<section> opens the example study.
    const params = new URLSearchParams(window.location.search);
    const study = params.get("study");
    const bbox = parseBBox(params.get("bbox"));
    if (isStudyTab(study)) setTab(study);
    else if (bbox) loadArea(bbox);
  }, []);

  useEffect(() => {
    // Optional: without it the map keeps its built-in default view.
    getRegion().then(setRegion).catch(() => {});
  }, []);

  // The example study's cameras and runs are fetched the first time a study tab opens, not on the check-up.
  const studyOpened = useRef(false);
  useEffect(() => {
    if (tab === "explore" || studyOpened.current) return;
    studyOpened.current = true;
    Promise.all([getCameras(), getRuns()])
      .then(([c, r]) => {
        setCameras(c);
        setRuns(r);
        const fresh = r.find((x) => !x.stale) ?? r[0];
        if (fresh) setRunId(fresh.id);
      })
      .catch((e: Error) => {
        studyOpened.current = false; // try again on the next study tab switch
        setError(`API unreachable: ${e.message}`);
      });
  }, [tab]);

  useEffect(() => {
    if (runId == null) return;
    setDetail(null);
    setDay(null);
    setFocus(null);
    setReveal(0);
    getRun(runId).then(setDetail).catch((e: Error) => setError(e.message));
  }, [runId]);

  function switchTab(t: Tab) {
    setTab(t);
    setPickMode(null);
    setDrawing(false);
    setRouteDraft(null);
    setPageUrl(t, area?.bbox ?? null);
    if (t === "driver" && detail?.stored === false && runId != null) {
      setDetail(null);
      getRun(runId).then(setDetail).catch((e: Error) => setError(e.message));
    }
    if (t === "yourweek" && detail?.stored !== false) setDetail(null);
  }

  const regionName = region?.name ?? FALLBACK_REGION_NAME;
  const scenarioTown = region?.scenario_town ?? FALLBACK_SCENARIO_TOWN;
  // Town for this run's hypothetical cameras: the form's pick, if it is still a region town.
  const towns = region?.towns ?? [];
  const formTown = towns.includes(form.town) ? form.town : scenarioTown;
  const showDriver = tab === "driver" || (tab === "yourweek" && detail?.stored === false);

  // Real cameras plus any synthetic scenario cameras this run used.
  const runCameras = useMemo<CameraCollection | null>(() => {
    const scn = detail?.run.scenario;
    if (!cameras || !scn?.cameras.length) return cameras;
    const extra = scn.cameras.map((c, i) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [c.lon, c.lat] as [number, number] },
      properties: {
        kind: "camera" as const, camera_id: -(i + 1), osm_id: c.label, town: scn.town ?? "", has_direction: true,
        directions_deg: c.directions_deg, direction_ambiguous: false, alt_directions_deg: null, snap_ambiguous: false,
        manufacturer: null, camera_kind: "scenario" as const, lot_name: null,
      },
    }));
    return { ...cameras, features: [...cameras.features, ...extra] };
  }, [cameras, detail]);

  const days = useMemo(() => {
    const ds = new Set<string>();
    for (const t of detail?.trips.features ?? []) ds.add(dayKey(t.properties.depart));
    return [...ds].sort();
  }, [detail]);

  const view = useMemo(() => {
    const inDay = (iso: string) => !day || dayKey(iso) === day;
    return {
      trips: (detail?.trips.features ?? []).filter((t) => inDay(t.properties.depart)),
      passes: (detail?.passes ?? []).filter((p) => inDay(p.time)),
      reads: (detail?.reads ?? []).filter((r) => inDay(r.time)),
    };
  }, [detail, day]);

  const truth = useMemo(() => {
    const km_ = view.trips.reduce((s, t) => s + t.properties.length_m, 0);
    const captured = view.passes.filter((p) => p.captured).length;
    const lost = view.passes.filter((p) => p.captured && p.noise_outcome !== "read").length;
    return { trips: view.trips.length, km: km_, passes: view.passes.length, captured, lost };
  }, [view]);

  const cameraCount = new Set(view.reads.map((r) => r.camera_label)).size;
  const misreads = view.reads.filter((r) => r.misread).length;
  const run = detail?.run;

  async function onSimulate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const run_id = await simulateJob({ generator: form.generator, template: form.template || undefined,
                                         weeks: form.weeks, seed: form.seed, extra_cameras: form.extra,
                                         scenario_town: form.extra > 0 && towns.includes(form.town) ? form.town : undefined }, setJob);
      setRuns(await getRuns());
      setRunId(run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setJob(null);
    }
  }

  return (
    <div className={`shell mode-${mode}`}>
      <div className="sr-only" role="status" aria-live="polite">{announcement}</div>
      <aside className="dossier">
        <header className="masthead">
          <div className="kicker">Plate Trail · location-privacy check-up</div>
          {tab === "explore" ? (
            <>
              <h1>Sensors on your map</h1>
              <p className="lede">
                Look up public fixed-sensor locations for any area, check the routes you drive, and see
                what changed since your last visit. Your routes stay in this browser.
              </p>
            </>
          ) : (
            <>
              <h1>Example study: what the cameras saw</h1>
              <p className="lede">
                One synthetic driver, real camera positions in {regionName}. Compare the read log an
                agency would hold with the week the driver actually drove.
              </p>
            </>
          )}
        </header>

        <nav className="tabs" role="tablist" aria-label="section" onKeyDown={onTabListKeyDown}>
          <button role="tab" aria-selected={tab === "explore"} tabIndex={tabStop(tab === "explore")} className={tab === "explore" ? "on" : ""} onClick={() => switchTab("explore")}>Check-up</button>
          <span className="tabs-group" aria-hidden="true">Example study</span>
          {STUDY_TABS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} tabIndex={tabStop(tab === k)} aria-label={`Example study: ${label}`} className={tab === k ? "on" : ""} onClick={() => switchTab(k)}>{label}</button>
          ))}
        </nav>

        {tab === "explore" && (
          <SinceLastVisit areas={savedAreas} routes={routes} ready={!areaLoading} checks={routeChecks}
            onCheckRoutes={async (ids) => { for (const id of ids) await runRouteCheck(id); }}
            onOpenArea={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }}
            onShowRoute={(id) => { setRouteDraft(null); setShownRoute(id); }} />
        )}
        {tab === "explore" && (
          <ExploreView area={area} loading={areaLoading} error={areaError} shrunk={areaShrunk} onExplore={exploreView}
            drawing={drawing} onDrawToggle={() => { setRouteDraft(null); setDrawing(!drawing); }} selectedId={sensorId} onSelect={setSensorId}
            change={areaChange} onForget={() => forgetLooks((k) => k.startsWith("area:"))}
            onPick={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }} />
        )}
        {tab === "explore" && (
          <MyAreas areas={savedAreas} storageOk={areasSaved} current={area?.bbox ?? null} loading={areaLoading}
            onOpen={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }}
            onSave={(name) => area && updateAreas(addArea(savedAreas, name, area.bbox))}
            onRename={(id, name) => updateAreas(renameArea(savedAreas, id, name))}
            onDelete={(id) => updateAreas(removeArea(savedAreas, id))} onClearAll={() => updateAreas([])} />
        )}
        {tab === "explore" && (
          <CompareAreas areas={savedAreas} onOpen={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }} />
        )}
        {tab === "explore" && (
          <MyRoutes routes={routes} storageOk={routesSaved} draft={routeDraft}
            onAdd={() => { setDrawing(false); setShownRoute(null); setRouteDraft({ start: null, end: null }); }}
            onCancel={() => setRouteDraft(null)} onSave={saveDraft} shownId={shownRoute} onShow={setShownRoute}
            checks={routeChecks} onCheck={runRouteCheck} focus={stepFocus} onFocus={setStepFocus}
            onRename={(id, name) => updateRoutes(renameRoute(routes, id, name))}
            onDelete={(id) => updateRoutes(removeRoute(routes, id))} onClearAll={() => updateRoutes([])} />
        )}
        {tab === "explore" && (
          <CompareRoutes routes={routes} checks={routeChecks} onCheck={runRouteCheck}
            onShow={(id) => { setRouteDraft(null); setShownRoute(id); }} />
        )}
        {tab === "population" && <PopulationView scenarioTown={scenarioTown} notes={region?.notes ?? {}} />}
        {tab === "yourweek" && (
          <YourWeek pins={pins} pickMode={pickMode} setPickMode={setPickMode}
                    onResult={(d) => { setDetail(d); setDay(null); setReveal(1); setMode("saw");
                      setTimeout(() => document.querySelector(".yw-banner")?.scrollIntoView({ behavior: "smooth" }), 60); }} />
        )}

        {tab === "driver" && (
        <section className="picker">
          <label htmlFor="run">Stored run</label>
          <select id="run" value={runId ?? ""} onChange={(e) => setRunId(Number(e.target.value))}>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} · {templateName(r.generator)} · {r.weeks} wk · seed {r.seed} · {r.summary.reads} reads
                {r.extra_cameras ? ` · +${r.extra_cameras} hypothetical cams` : ""}
                {r.stale ? " · stale" : ""}
              </option>
            ))}
          </select>
          <details className="simulate">
            <summary>Simulate a new driver</summary>
            <form onSubmit={onSimulate}>
              <select value={form.generator} aria-label="routine source"
                      onChange={(e) => setForm({ ...form, generator: e.target.value as "nhts" | "template", template: "" })}>
                <option value="nhts">NHTS</option>
                <option value="template">template</option>
              </select>
              <select value={form.template} aria-label="persona" onChange={(e) => setForm({ ...form, template: e.target.value })}>
                <option value="">any</option>
                {(form.generator === "nhts" ? ["worker", "student", "non_worker"] : ["commuter", "student", "shift_worker"]).map(
                  (t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
              </select>
              <input type="number" min={1} max={8} value={form.weeks} aria-label="weeks"
                     onChange={(e) => setForm({ ...form, weeks: Number(e.target.value) })} />
              <span className="unit">wk</span>
              <input type="number" min={0} value={form.seed} aria-label="seed"
                     onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })} />
              <span className="unit">seed</span>
              <input type="number" min={0} max={200} value={form.extra} aria-label="extra cameras"
                     title={`Hypothetical cameras added in ${formTown}. Placement is simulated: arterials chosen in proportion to length, at least 300 m apart, one direction each.`}
                     onChange={(e) => setForm({ ...form, extra: Number(e.target.value) })} />
              <span className="unit">+hypothetical cams</span>
              {towns.length > 1 && form.extra > 0 && (
                <select value={formTown} aria-label="town for hypothetical cameras"
                        onChange={(e) => setForm({ ...form, town: e.target.value })}>
                  {towns.map((t) => <option key={t} value={t}>in {t}</option>)}
                </select>
              )}
              <button disabled={busy}>{busy ? jobLabel(job) : "run"}</button>
            </form>
          </details>
        </section>
        )}

        {error && tab !== "explore" && <div className="error">{error}</div>}
        {showDriver && (<>
        {tab === "yourweek" && <div className="error stale yw-banner">Your week, simulated just now and not stored.</div>}
        {run?.stale && (
          <div className="error stale">
            Stale run: cameras were reloaded after it was simulated, so camera references may not match.
            Simulate a new driver for current data.
          </div>
        )}

        {run && (
          <section className="tag">
            <div className="plate-tag">
              <span className="plate-state">{run.plate_state}</span>
              <span className="plate-num">{run.plate}</span>
            </div>
            <div className="tag-meta">
              {templateName(run.generator)} · {run.weeks} week{run.weeks > 1 ? "s" : ""} from {run.start_date} · seed{" "}
              {run.seed}
              <br />
              <span className="dim">synthetic plate; state ZZ does not exist</span>
            </div>
          </section>
        )}

        <section className="switch" role="tablist" aria-label="view" onKeyDown={onTabListKeyDown}>
          <button role="tab" aria-selected={mode === "saw"} tabIndex={tabStop(mode === "saw")} className={mode === "saw" ? "on" : ""} onClick={() => setMode("saw")}>
            <span className="sw-k">What the cameras saw</span>
            <span className="sw-v">{view.reads.length}<small> reads · {cameraCount} cam{cameraCount === 1 ? "" : "s"}</small></span>
          </button>
          <button role="tab" aria-selected={mode === "happened"} tabIndex={tabStop(mode === "happened")} className={mode === "happened" ? "on" : ""} onClick={() => setMode("happened")}>
            <span className="sw-k">What actually happened</span>
            <span className="sw-v">{truth.trips}<small> trips · {km(truth.km * 1)}</small></span>
          </button>
        </section>

        <section className="readout">
          {mode === "saw" ? (
            <p>
              The agency holds <b>{view.reads.length}</b> timestamped plate reads
              {misreads > 0 && <> (<b>{misreads}</b> misread, though nothing in the log says so)</>}. No routes,
              no stops, no purposes: only where the {cameraCount} camera{cameraCount === 1 ? "" : "s"} happened to be.
            </p>
          ) : (
            <p>
              The driver made <b>{truth.trips}</b> trips over <b>{km(truth.km)}</b> and passed <b>{truth.passes}</b>{" "}
              camera{truth.passes === 1 ? "" : "s"}. <b>{truth.captured}</b> faced the right way; <b>{truth.lost}</b> of
              those reads were lost to misses or downtime.
            </p>
          )}
        </section>

        {detail && <NaiveCard guess={detail.naive_guess} mode={mode} />}
        {detail?.inference && <RevealCard inference={detail.inference} reveal={reveal} setReveal={setReveal} mode={mode} />}

        <section className="controls">
          <div className="days">
            <button className={!day ? "on" : ""} onClick={() => setDay(null)}>all</button>
            {days.map((d) => (
              <button key={d} className={day === d ? "on" : ""} onClick={() => setDay(d)} title={d}>
                {parts(d).weekday.slice(0, 2)}<small>{d.slice(8)}</small>
              </button>
            ))}
          </div>
          <div className="layers">
            <label className={mode === "saw" ? "disabled" : ""} title={mode === "saw" ? "The cameras never saw the routes" : ""}>
              <input type="checkbox" checked={layers.routes} disabled={mode === "saw"}
                     onChange={(e) => setLayers({ ...layers, routes: e.target.checked })} /> true routes
            </label>
            <label className={mode === "saw" ? "disabled" : ""}>
              <input type="checkbox" checked={layers.skipped} disabled={mode === "saw"}
                     onChange={(e) => setLayers({ ...layers, skipped: e.target.checked })} /> uncaptured passes
            </label>
            <label>
              <input type="checkbox" checked={layers.cameras} onChange={(e) => setLayers({ ...layers, cameras: e.target.checked })} /> cameras
            </label>
          </div>
        </section>

        <LogTable mode={mode} reads={view.reads} passes={view.passes} focusLabel={focus} onFocus={setFocus} />
        </>)}
      </aside>

      {tab === "explore" ? (
      <main className="stage">
        <AreaMap area={area} initialView={region?.map ?? null} onView={(b) => { viewBox.current = b; }}
          drawing={drawing} onDraw={exploreDrawn} selectedId={sensorId} onSelect={setSensorId}
          placing={!!routeDraft && !routeDraft.end} onPlace={placeRoutePoint} routeMarks={routeMarks} routeLegs={routeLegs}
          stepFocus={routeLegs ? stepFocus : null} />
        {drawing && <div className="draw-hint" role="status">Drag on the map to draw a box · Esc to cancel</div>}
        {routeDraft && !routeDraft.end && (
          <div className="draw-hint" role="status">Click the route&apos;s {routeDraft.start ? "end" : "start"} point · Esc to cancel</div>
        )}
        <div className="legend">
          <span><i className="lg-sensor" />sensor, direction known</span>
          <span><i className="lg-undir lg-sensor-undir" />direction not recorded</span>
          <span><i className="lg-box" />explored area</span>
          {routeMarks && !routeLegs && <span><i className="lg-route" />route start (filled) and end, straight line</span>}
          {routeLegs && <span><i className="lg-drive" />route by road (way back fainter)</span>}
          {routeLegs && <span><i className="lg-pass" />sensor passed: ringed if it would read the trip</span>}
        </div>
      </main>
      ) : (
      <main className="stage">
        <MapView
          cameras={tab === "population" ? cameras : runCameras}
          trips={showDriver ? view.trips : []}
          passes={showDriver ? view.passes : []}
          reads={showDriver ? view.reads : []}
          mode={mode}
          layers={layers}
          focusLabel={focus}
          fitKey={detail ? `${detail.run.id}:${day ?? "all"}` : ""}
          guess={showDriver ? detail?.naive_guess ?? null : null}
          inference={showDriver ? detail?.inference ?? null : null}
          reveal={reveal}
          pickMode={tab === "yourweek" ? pickMode : null}
          onPick={(kind, pt) => { setPins({ ...pins, [kind]: pt }); setPickMode(null); }}
          pins={tab === "yourweek" ? pins : undefined}
          initialView={region?.map ?? null}
          scenarioTown={detail?.run.scenario?.town ?? scenarioTown}
        />
        <div className="legend">
          {mode === "saw" ? (
            <>
              <span><i className="lg-read" />read (size = count)</span>
              <span><i className="lg-trail" />implied sequence</span>
            </>
          ) : (
            <>
              <span><i className="lg-truth" />true route</span>
              <span><i className="lg-ring lg-ring-read" />read</span>
              <span><i className="lg-ring lg-ring-lost" />captured, lost</span>
              <span><i className="lg-ring lg-ring-skip" />wrong direction</span>
            </>
          )}
          <span><i className="lg-arrow" />camera (arrow = facing)</span>
          <span><i className="lg-arrow lg-lot" />lot</span>
          <span><i className="lg-arrow lg-svc" />service street</span>
          <span><i className="lg-undir" />no direction</span>
          <span><i className="lg-guess" />naive guess</span>
          {detail?.run.scenario && <span><i className="lg-arrow lg-scn" />hypothetical camera, simulated placement (+{detail.run.scenario.extra_cameras})</span>}
          {mode === "happened" && <span><i className="lg-truthpin" />true home / work</span>}
        </div>
        <div className="mode-stamp">{mode === "saw" ? "RECORDED" : "GROUND TRUTH"}</div>
      </main>
      )}
    </div>
  );
}
