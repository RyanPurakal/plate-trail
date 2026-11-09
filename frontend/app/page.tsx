"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import ExploreView from "@/components/ExploreView";
import MyAreas from "@/components/MyAreas";
import CompareAreas from "@/components/CompareAreas";
import CompareRoutes from "@/components/CompareRoutes";
import MoveData from "@/components/MoveData";
import SinceLastVisit from "@/components/SinceLastVisit";
import MyRoutes, { type RouteCheckState, type RouteDraft, type StepFocus } from "@/components/MyRoutes";
import { checkRoute, getArea, getRegion, type AreaResult, type Region } from "@/lib/api";
import { formatBBox, parseBBox, viewToBBox, type BBox } from "@/lib/area";
import { makeBackup, mergeBackup, mergeSummary, type Backup } from "@/lib/backup";
import { areaKey, areaSnapshot, forgetLooks, loadSnapshots, makeSnapshot, recordLook, routeKey, saveSnapshots, type SnapshotChange } from "@/lib/snapshots";
import { addArea, AREAS_KEY, loadAreas, removeArea, renameArea, saveAreas, type SavedArea } from "@/lib/areas";
import { addRoute, loadRoutes, removeRoute, renameRoute, saveRoutes, STORAGE_KEY, type Pt, type SavedRoute } from "@/lib/routes";
import { areaAnnouncement, nextAnnouncement, routeAnnouncement } from "@/lib/announce";
import { latestOnly } from "@/lib/latest";

const AreaMap = dynamic(() => import("@/components/AreaMap"), { ssr: false });

/** Keep the explored box (and nothing else) in the address bar so the page can be shared. */
function setPageUrl(bbox: BBox | null) {
  window.history.replaceState(null, "", window.location.pathname + (bbox ? `?bbox=${formatBBox(bbox)}` : ""));
}

export default function Home() {
  const [region, setRegion] = useState<Region | null>(null);
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
  const areaRequests = useRef(latestOnly());

  async function loadArea(bbox: BBox) {
    // Some openers (Compare, Since your last visit) stay clickable while an area loads; the newest request wins.
    const ticket = areaRequests.current.start();
    setAreaLoading(true);
    setAreaError(null);
    announce("Loading public map data for this area…");
    try {
      const a = await getArea(bbox);
      if (!areaRequests.current.isCurrent(ticket)) return; // superseded: not shown, so not recorded as a look
      setArea(a);
      // Saved areas' looks are kept however long ago they were; read fresh so another tab's saves count too.
      const pinned = new Set(loadAreas().map((x) => areaKey(x.bbox)));
      const change = recordLook(areaKey(a.bbox), areaSnapshot(a), pinned);
      setAreaChange(change);
      announce(areaAnnouncement(a, change));
      setSensorId(null);
      setPageUrl(a.bbox);
    } catch (e) {
      if (areaRequests.current.isCurrent(ticket)) setAreaError((e as Error).message);
    } finally {
      if (areaRequests.current.isCurrent(ticket)) setAreaLoading(false);
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

  function importSaved(file: Backup) {
    const merged = mergeBackup({ routes, areas: savedAreas, snapshots: loadSnapshots() }, file);
    updateRoutes(merged.routes);
    updateAreas(merged.areas);
    saveSnapshots(merged.snapshots);
    return mergeSummary(merged);
  }

  // Results stay in page memory only; reloading the page or deleting the route drops them.
  async function runRouteCheck(id: string) {
    const r = routes.find((x) => x.id === id);
    if (!r) return;
    setRouteChecks((c) => ({ ...c, [id]: { loading: true, result: null, error: null } }));
    announce(`Checking ${r.name}…`);
    try {
      const result = await checkRoute(r.start, r.end);
      const change = recordLook(routeKey(id), makeSnapshot(result.legs.flatMap((l) => l.steps.map((st) => st.sensor_id))));
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
    // An area link (?bbox=w,s,e,n) loads that area.
    const bbox = parseBBox(new URLSearchParams(window.location.search).get("bbox"));
    if (bbox) loadArea(bbox);
  }, []);

  useEffect(() => {
    // Optional: without it the map keeps its built-in default view.
    getRegion().then(setRegion).catch(() => {});
  }, []);

  return (
    <div className="shell">
      <div className="sr-only" role="status" aria-live="polite">{announcement}</div>
      <aside className="dossier">
        <header className="masthead">
          <div className="sign">
            <div className="sign-tab" aria-hidden="true">Check-up</div>
            <div className="kicker">Location-privacy check-up</div>
            <h1>Plate Trail</h1>
            <div className="sign-sub">
              <span>Sensors on your map</span>
              <svg className="sign-arrow" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 18 L17 7 M9 7 H17 V15" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="square" />
              </svg>
            </div>
          </div>
          <p className="lede">
            Look up public fixed-sensor locations for any area, check the routes you drive, and see
            what changed since your last visit. Your routes stay in this browser.
          </p>
        </header>

        <SinceLastVisit areas={savedAreas} routes={routes} ready={!areaLoading} checks={routeChecks}
          onCheckRoutes={async (ids) => { for (const id of ids) await runRouteCheck(id); }}
          onOpenArea={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }}
          onShowRoute={(id) => { setRouteDraft(null); setShownRoute(id); }} />
        <ExploreView area={area} loading={areaLoading} error={areaError} shrunk={areaShrunk} onExplore={exploreView}
          drawing={drawing} onDrawToggle={() => { setRouteDraft(null); setDrawing(!drawing); }} selectedId={sensorId} onSelect={setSensorId}
          change={areaChange} onForget={() => forgetLooks((k) => k.startsWith("area:"))}
          onPick={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }} />
        <MyAreas areas={savedAreas} storageOk={areasSaved} current={area?.bbox ?? null} loading={areaLoading}
          onOpen={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }}
          onSave={(name) => area && updateAreas(addArea(savedAreas, name, area.bbox))}
          onRename={(id, name) => updateAreas(renameArea(savedAreas, id, name))}
          onDelete={(id) => updateAreas(removeArea(savedAreas, id))} onClearAll={() => updateAreas([])} />
        <CompareAreas areas={savedAreas} onOpen={(b) => { setDrawing(false); setAreaShrunk(false); loadArea(b); }} />
        <MyRoutes routes={routes} storageOk={routesSaved} draft={routeDraft}
          onAdd={() => { setDrawing(false); setShownRoute(null); setRouteDraft({ start: null, end: null }); }}
          onCancel={() => setRouteDraft(null)} onSave={saveDraft} shownId={shownRoute} onShow={setShownRoute}
          checks={routeChecks} onCheck={runRouteCheck} focus={stepFocus} onFocus={setStepFocus}
          onRename={(id, name) => updateRoutes(renameRoute(routes, id, name))}
          onDelete={(id) => updateRoutes(removeRoute(routes, id))} onClearAll={() => updateRoutes([])} />
        <CompareRoutes routes={routes} checks={routeChecks} onCheck={runRouteCheck}
          onShow={(id) => { setRouteDraft(null); setShownRoute(id); }} />
        <MoveData hasSaved={routes.length + savedAreas.length > 0}
          onExport={() => makeBackup({ routes, areas: savedAreas, snapshots: loadSnapshots() })}
          onImport={importSaved} />
      </aside>

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
    </div>
  );
}
