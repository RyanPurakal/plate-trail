"use client";

import { useEffect, useState } from "react";
import type { RouteCheck, RouteLeg, RouteStep } from "@/lib/api";
import type { SnapshotChange } from "@/lib/snapshots";
import ChangeNote from "./ChangeNote";
import RouteHistory from "./RouteHistory";
import { MAX_NAME, MAX_ROUTES, nextRouteName, straightKm, type Pt, type SavedRoute } from "@/lib/routes";

export type RouteDraft = { start: Pt | null; end: Pt | null };
export type RouteCheckState = {
  loading: boolean;
  result: RouteCheck | null;
  error: string | null;
  change?: SnapshotChange | null; // sensors passed vs this browser's last check of the route
};
export type StepFocus = { key: string; at: Pt; cameraId: string }; // timeline step shown on the map

type Props = {
  routes: SavedRoute[];
  storageOk: boolean; // false when the browser refused to save (private mode, blocked storage)
  draft: RouteDraft | null; // non-null while a new route's points are being placed on the map
  onAdd: () => void;
  onCancel: () => void;
  onSave: (name: string) => void;
  shownId: string | null; // route drawn on the map
  onShow: (id: string | null) => void;
  checks: Record<string, RouteCheckState>; // route check results, kept in page memory only
  onCheck: (id: string) => void;
  focus: StepFocus | null;
  onFocus: (f: StepFocus | null) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
};

const km = (r: { start: Pt; end: Pt }) => `${straightKm(r.start, r.end).toFixed(1)} km apart`;
const minutes = (s: number) => `${Math.max(1, Math.round(s / 60))} min`;
const clock = (s: number) => {
  const t = Math.round(s);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};

const REASONS: Record<string, string> = {
  captured: "faces this direction of traffic",
  wrong_direction: "faces the other direction of traffic",
  captured_undirected_best: "no direction recorded, so counted as reading both ways",
  missed_undirected_worst: "no direction recorded, counted as not reading here",
};

const stepPlace = (st: RouteStep) => st.road_name || st.label || "Unnamed road";

type LegProps = { leg: RouteLeg; focus: StepFocus | null; onFocus: (f: StepFocus | null) => void };

/** One direction of a checked route: totals, then a timeline of each sensor passed in order. */
function LegSummary({ leg, focus, onFocus }: LegProps) {
  return (
    <div className="mr-leg">
      <div className="mr-leg-head">{leg.direction === "outbound" ? "Start to end" : "Way back"}</div>
      <div className="ex-row"><span>By road</span><span>{(leg.length_m / 1000).toFixed(1)} km · {minutes(leg.duration_s)}</span></div>
      <div className="ex-row"><span>Sensors passed</span><span>{leg.sensors_passed}</span></div>
      <div className="ex-row">
        <span>Passes that would record it</span>
        <span>{leg.reads} of {leg.steps.length}</span>
      </div>
      <ol className="mr-steps" aria-label={`Timeline, ${leg.direction === "outbound" ? "start to end" : "way back"}`}>
        <li className="mr-step-end"><span className="mr-when">0:00</span><span>Leave</span></li>
        {leg.steps.map((st, i) => {
          const key = `${leg.direction}:${i}`;
          const on = focus?.key === key;
          const at: Pt | null = st.lon != null && st.lat != null ? [st.lon, st.lat] : null;
          return (
            <li key={key} className={`${st.read ? "read" : "pass"}${on ? " on" : ""}`}>
              <button className="mr-step" aria-pressed={on} disabled={!at}
                onClick={() => onFocus(on || !at ? null : { key, at, cameraId: st.camera_id })}>
                <span className="mr-when">{clock(st.offset_s)}</span>
                <span>
                  <span className="mr-step-what">{st.read ? "Would record" : "Passes, not recorded"}</span>
                  <span className="dim"> · {stepPlace(st)} · {(st.distance_m / 1000).toFixed(1)} km in</span>
                  <span className="mr-step-why dim">{REASONS[st.reason] ?? st.reason}</span>
                </span>
              </button>
            </li>
          );
        })}
        <li className="mr-step-end"><span className="mr-when">{clock(leg.duration_s)}</span><span>Arrive</span></li>
      </ol>
      {leg.steps.length === 0 && <div className="nb-note">No mapped sensors along this drive.</div>}
    </div>
  );
}

/** Result of checking one route: both directions, or why it couldn't be checked. */
function CheckResult({ state, focus, onFocus }: { state: RouteCheckState } & Omit<LegProps, "leg">) {
  if (state.loading) {
    return (
      <div className="nb-note" role="status">
        Working out the route by road… For a place outside the example study area, the first check downloads its
        roads from OpenStreetMap and can take a minute.
      </div>
    );
  }
  if (state.error) return <div className="error" role="alert">{state.error}</div>;
  const r = state.result;
  if (!r) return null;
  return (
    <div aria-live="polite">
      {r.legs.map((leg) => <LegSummary key={leg.direction} leg={leg} focus={focus} onFocus={onFocus} />)}
      {state.change !== undefined && <ChangeNote change={state.change} what="along this route" />}
      <div className="nb-note">
        Fastest route by road on {r.network.kind === "region" ? `the ${r.network.name} study roads` : "OpenStreetMap roads around this route"},
        using mapped sensors only. A sensor with a known direction is counted for trips travelling the way it faces;
        one with no recorded direction is counted both ways. Times are minutes and seconds from leaving at modelled road speeds;
        click a step to see it on the map. This check was worked out on the server and not stored there.
      </div>
    </div>
  );
}

/** Sidebar list of the routes saved in this browser, with add / rename / delete. */
export default function MyRoutes({ routes, storageOk, draft, onAdd, onCancel, onSave, shownId, onShow, checks, onCheck, focus, onFocus, onRename, onDelete, onClearAll }: Props) {
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null); // route id, or "all"

  useEffect(() => {
    if (draft?.end) setName(nextRouteName(routes));
  }, [draft?.end, routes]);

  function save(e: React.FormEvent) {
    e.preventDefault();
    onSave(name);
  }

  function rename(e: React.FormEvent) {
    e.preventDefault();
    if (editing) onRename(editing.id, editing.name);
    setEditing(null);
  }

  const full = routes.length >= MAX_ROUTES;

  return (
    <section className="naive my-routes" aria-labelledby="mr-title">
      <div className="nb-head">
        <span id="mr-title">My routes</span>
        <span className="nb-badge">on this device</span>
      </div>
      <div className="nb-note">
        Routes are saved only in this browser&apos;s local storage. They are not sent to or stored on the server, and
        clearing site data removes them.
      </div>
      {!storageOk && (
        <div className="error" role="alert">This browser is not allowing local storage, so routes last only until the page is closed.</div>
      )}

      {routes.length === 0 && !draft && (
        <div className="nb-note">No routes yet. Add one you drive often, such as a commute or a school run.</div>
      )}

      {routes.length > 0 && (
        <ul className="mr-list">
          {routes.map((r) => (
            <li key={r.id} className={shownId === r.id ? "on" : ""}>
              {editing?.id === r.id ? (
                <form className="mr-edit" onSubmit={rename}>
                  <label className="sr-only" htmlFor={`mr-name-${r.id}`}>New name for {r.name}</label>
                  <input id={`mr-name-${r.id}`} value={editing.name} maxLength={MAX_NAME} autoFocus
                    onChange={(e) => setEditing({ id: r.id, name: e.target.value })}
                    onKeyDown={(e) => { if (e.key === "Escape") setEditing(null); }} />
                  <button type="submit" className="ex-share" disabled={!editing.name.trim()}>Save</button>
                  <button type="button" className="ex-share" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <button className="mr-name" aria-pressed={shownId === r.id} onClick={() => onShow(shownId === r.id ? null : r.id)}>
                    {r.name}<span className="dim"> · {km(r)}</span>
                  </button>
                  {confirm === r.id ? (
                    <span className="mr-tools">
                      <button className="ex-share" onClick={() => { onDelete(r.id); setConfirm(null); }}>Delete</button>
                      <button className="ex-share" onClick={() => setConfirm(null)}>Keep</button>
                    </span>
                  ) : (
                    <span className="mr-tools">
                      <button className="ex-share" aria-label={`Rename ${r.name}`} onClick={() => setEditing({ id: r.id, name: r.name })}>Rename</button>
                      <button className="ex-share" aria-label={`Delete ${r.name}`} onClick={() => setConfirm(r.id)}>Delete</button>
                    </span>
                  )}
                  {shownId === r.id && (
                    <div className="mr-check">
                      {!checks[r.id]?.loading && (
                        <button className="ex-share" onClick={() => onCheck(r.id)}>
                          {checks[r.id]?.result || checks[r.id]?.error ? "Check again" : "Check this route"}
                        </button>
                      )}
                      {checks[r.id] && <CheckResult state={checks[r.id]} focus={focus} onFocus={onFocus} />}
                      {checks[r.id]?.result && <RouteHistory key={r.id} start={r.start} end={r.end} />}
                    </div>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {draft ? (
        <div className="mr-draft" aria-live="polite">
          {!draft.start && <div className="nb-note">Click the map where the route starts. Esc cancels.</div>}
          {draft.start && !draft.end && <div className="nb-note">Now click where the route ends.</div>}
          {draft.start && draft.end && (
            <form className="mr-edit" onSubmit={save}>
              <label htmlFor="mr-new">Name this route</label>
              <input id="mr-new" value={name} maxLength={MAX_NAME} autoFocus placeholder="e.g. Commute"
                onChange={(e) => setName(e.target.value)} />
              <button type="submit" className="ex-share">Save route</button>
            </form>
          )}
          {draft.start && draft.end && (
            <div className="nb-note">The line on the map joins the two points. Save the route, then use &ldquo;Check this route&rdquo; to see it by road.</div>
          )}
          <button className="ex-share" onClick={onCancel}>Cancel</button>
        </div>
      ) : (
        <div className="ex-actions">
          <button className="ex-share" onClick={onAdd} disabled={full}>Add a route</button>
          {routes.length > 0 && (confirm === "all" ? (
            <>
              <button className="ex-share" onClick={() => { onClearAll(); setConfirm(null); }}>Remove all</button>
              <button className="ex-share" onClick={() => setConfirm(null)}>Keep</button>
            </>
          ) : (
            <button className="ex-share" onClick={() => setConfirm("all")}>Remove all from this device</button>
          ))}
        </div>
      )}
      {full && !draft && <div className="nb-note">Up to {MAX_ROUTES} routes can be saved. Delete one to add another.</div>}
    </section>
  );
}
