"use client";

import { useEffect, useState } from "react";
import type { RouteCheck, RouteLeg } from "@/lib/api";
import type { SavedRoute } from "@/lib/routes";
import type { RouteCheckState } from "./MyRoutes";

type Props = {
  routes: SavedRoute[];
  checks: Record<string, RouteCheckState>; // route check results, kept in page memory only
  onCheck: (id: string) => Promise<void>;
  onShow: (id: string) => void;
};

const leg = (r: RouteCheck, d: RouteLeg["direction"]) => r.legs.find((l) => l.direction === d);
const minutes = (s: number) => `${Math.max(1, Math.round(s / 60))} min`;

type Row = [string, (r: RouteCheck) => string];
const legRows = (d: RouteLeg["direction"], name: string): Row[] => [
  [`${name}: by road`, (r) => { const l = leg(r, d); return l ? `${(l.length_m / 1000).toFixed(1)} km · ${minutes(l.duration_s)}` : "–"; }],
  [`${name}: sensors passed`, (r) => String(leg(r, d)?.sensors_passed ?? "–")],
  [`${name}: passes that would record it`, (r) => { const l = leg(r, d); return l ? `${l.reads} of ${l.steps.length}` : "–"; }],
];

const ROWS: Row[] = [
  ...legRows("outbound", "Start to end"),
  ...legRows("return", "Way back"),
  ["Different sensors passed", (r) => String(new Set(r.legs.flatMap((l) => l.steps.map((st) => st.camera_id))).size)],
  ["Roads used", (r) => (r.network.kind === "region" ? `${r.network.name} study roads` : "OpenStreetMap roads")],
];

/**
 * Two saved routes side by side, from the same page-memory checks as "Check this route".
 * Routes not checked yet are checked when Compare is pressed; nothing is stored on the server.
 */
export default function CompareRoutes({ routes, checks, onCheck, onShow }: Props) {
  const [pick, setPick] = useState<[string, string]>(["", ""]);
  const [shown, setShown] = useState(false);
  const [loading, setLoading] = useState(false);

  // Keep the picks pointing at saved routes (defaults: the first two) as the list changes.
  useEffect(() => {
    const ids = routes.map((r) => r.id);
    setPick(([a, b]) => {
      const na = ids.includes(a) ? a : ids[0] ?? "";
      const nb = ids.includes(b) && b !== na ? b : ids.find((id) => id !== na) ?? "";
      return na === a && nb === b ? [a, b] : [na, nb];
    });
  }, [routes]);
  useEffect(() => setShown(false), [pick]);

  const byId = (id: string) => routes.find((r) => r.id === id);

  async function compare() {
    setLoading(true);
    // One at a time: a first check outside the study area downloads roads, so don't start two at once.
    for (const id of pick) if (!checks[id]?.result) await onCheck(id);
    setLoading(false);
    setShown(true);
  }

  const busy = loading || pick.some((id) => checks[id]?.loading);

  return (
    <section className="naive" aria-labelledby="cr-title">
      <div className="nb-head">
        <span id="cr-title">Compare routes</span>
        <span className="nb-badge">on this device</span>
      </div>
      {routes.length < 2 ? (
        <div className="nb-note">Save two routes, for example two ways to work, to compare them side by side.</div>
      ) : (
        <>
          <div className="ca-picks">
            {(["A", "B"] as const).map((label, i) => (
              <label key={label}>
                <span className="ex-k">Route {label}</span>
                <select value={pick[i]} disabled={busy}
                  onChange={(e) => setPick(i === 0 ? [e.target.value, pick[1]] : [pick[0], e.target.value])}>
                  {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </label>
            ))}
          </div>
          {pick[0] === pick[1] && <div className="nb-note">Pick two different routes.</div>}
          <div className="ex-actions">
            <button className="ex-share" onClick={compare} disabled={busy || !pick[0] || pick[0] === pick[1]}>
              {busy ? "Checking routes…" : shown ? "Compare again" : "Compare"}
            </button>
          </div>
          {busy && (
            <div className="nb-note" role="status">
              Routes not checked yet are checked first. Outside the example study area, a first check downloads roads
              and can take a minute.
            </div>
          )}

          {shown && !busy && (
            <div aria-live="polite">
              <table className="ca-table">
                <thead>
                  <tr>
                    <th scope="col"><span className="sr-only">Measure</span></th>
                    {pick.map((id) => {
                      const r = byId(id);
                      return (
                        <th scope="col" key={id}>
                          {r?.name ?? "Removed route"}
                          {r && <button className="ex-share ca-open" onClick={() => onShow(id)}>Show</button>}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map(([label, value]) => (
                    <tr key={label}>
                      <th scope="row">{label}</th>
                      {pick.map((id) => {
                        const result = checks[id]?.result;
                        return <td key={id}>{result ? value(result) : "–"}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              {pick.map((id) => checks[id]?.error && (
                <div key={id} className="error" role="alert">{byId(id)?.name ?? "Route"}: {checks[id].error}</div>
              ))}
              <div className="nb-note">
                Uses the latest check of each route in this page; &ldquo;Check again&rdquo; on a route updates its
                column. Counts cover mapped sensors only. A sensor with a known direction is counted for trips the way it
                faces, so the two directions of the same route can differ. Results are kept in this page only.
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
