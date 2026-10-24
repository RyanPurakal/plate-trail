"use client";

import { useEffect, useState } from "react";
import { getArea } from "@/lib/api";
import { shortDate, type BBox } from "@/lib/area";
import type { SavedArea } from "@/lib/areas";
import type { SavedRoute } from "@/lib/routes";
import { areaKey, areaSnapshot, loadSnapshots, recordLook, routeKey, type SnapshotChange } from "@/lib/snapshots";
import type { RouteCheckState } from "./MyRoutes";

type AreaVisit = { id: string; status: "recent" | "first" | "error"; seen?: string } | { id: string; status: "done"; change: SnapshotChange };

type Props = {
  areas: SavedArea[];
  routes: SavedRoute[];
  ready: boolean; // false while the page is still loading an area of its own
  checks: Record<string, RouteCheckState>; // route check results, page memory only
  onCheckRoutes: (ids: string[]) => void;
  onOpenArea: (bbox: BBox) => void;
  onShowRoute: (id: string) => void;
};

// Saved areas looked at this recently are not fetched again on a return visit.
export const RECHECK_AFTER_MS = 60 * 60 * 1000;

// One run per page load, so switching tabs and back does not re-check.
let visitRun: Promise<AreaVisit[]> | null = null;

async function checkAreas(areas: SavedArea[], onProgress: (i: number) => void): Promise<AreaVisit[]> {
  const snaps = loadSnapshots();
  const pinned = new Set(areas.map((a) => areaKey(a.bbox)));
  const out: AreaVisit[] = [];
  for (const [i, a] of areas.entries()) {
    onProgress(i);
    const seen = snaps[areaKey(a.bbox)]?.seen;
    if (seen && Date.now() - new Date(seen).getTime() < RECHECK_AFTER_MS) {
      out.push({ id: a.id, status: "recent", seen });
      continue;
    }
    try {
      const r = await getArea(a.bbox);
      const change = recordLook(areaKey(a.bbox), areaSnapshot(r), pinned);
      out.push(change ? { id: a.id, status: "done", change } : { id: a.id, status: "first" });
    } catch {
      out.push({ id: a.id, status: "error" });
    }
  }
  return out;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function changeText(c: SnapshotChange): string {
  const parts = [
    c.added.length > 0 && `${plural(c.added.length, "sensor")} newly listed`,
    c.removed.length > 0 && `${c.removed.length} no longer listed`,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : "no sensors added or removed";
}

const changed = (c: SnapshotChange) => c.added.length + c.removed.length + c.updated.length > 0;

/** "Since your last visit": on return, saved areas are re-checked against this browser's last look at them;
 *  routes checked before can be re-checked with one click (they use the compute-only route check). */
export default function SinceLastVisit({ areas, routes, ready, checks, onCheckRoutes, onOpenArea, onShowRoute }: Props) {
  const [results, setResults] = useState<AreaVisit[] | null>(null);
  const [progress, setProgress] = useState<number | null>(null);

  useEffect(() => {
    if (!ready || (!visitRun && !areas.length)) return;
    let live = true;
    // Areas saved after the run started are not part of it; they show up on the next visit.
    visitRun ??= checkAreas(areas, (i) => live && setProgress(i));
    visitRun.then((r) => {
      if (!live) return;
      setResults(r);
      setProgress(null);
    });
    return () => { live = false; };
  }, [ready, areas]);

  const snaps = loadSnapshots();
  const checkedBefore = routes.filter((r) => snaps[routeKey(r.id)]);
  const routeBusy = checkedBefore.some((r) => checks[r.id]?.loading);
  const routeDone = checkedBefore.filter((r) => checks[r.id]?.result);

  if (!areas.length && !checkedBefore.length) return null;

  const byId = new Map(areas.map((a) => [a.id, a]));
  const shown = (results ?? []).filter((v) => byId.has(v.id));
  const withChange = shown.filter((v) => v.status === "done" && changed(v.change));

  return (
    <section className="naive visit" aria-live="polite">
      <div className="nb-head">
        <span>Since your last visit</span>
        <span className="nb-badge">this device</span>
      </div>

      {areas.length > 0 && progress !== null && (
        <div className="nb-note">Checking saved areas against public map data ({progress + 1} of {areas.length})…</div>
      )}

      {shown.length > 0 && (
        <>
          <div className="ex-k">Saved areas</div>
          {shown.some((v) => v.status === "done") && <div className="nb-note">
            {withChange.length === 0
              ? "No changes found in your saved areas."
              : `${plural(withChange.length, "saved area")} changed since you last looked.`}
          </div>}
          <ul className="mr-list">
            {shown.map((v) => {
              const a = byId.get(v.id)!;
              const note = v.status === "done"
                ? `since ${shortDate(v.change.since) ?? "last look"}: ${changeText(v.change)}${v.change.updated.length ? "; data updated" : ""}`
                : v.status === "recent" ? `looked at ${shortDate(v.seen ?? null) ?? "recently"}, within the last hour`
                : v.status === "first" ? "first look from this browser"
                : "couldn't be checked right now";
              return (
                <li key={v.id} className={v.status === "done" && changed(v.change) ? "on" : ""}>
                  <button className="mr-name" onClick={() => onOpenArea(a.bbox)}>
                    {a.name}<span className="dim"> · {note}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {checkedBefore.length > 0 && (
        <>
          <div className="ex-k">Routes you checked before</div>
          {routeDone.length > 0 && (
            <ul className="mr-list">
              {routeDone.map((r) => {
                const c = checks[r.id]?.change;
                return (
                  <li key={r.id}>
                    <button className="mr-name" onClick={() => onShowRoute(r.id)}>
                      {r.name}<span className="dim"> · {c ? `since ${shortDate(c.since) ?? "last check"}: ${changeText(c)}` : "checked"}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="ex-actions">
            <button className="ex-share" disabled={routeBusy}
              onClick={() => onCheckRoutes(checkedBefore.map((r) => r.id))}>
              {routeBusy ? "Checking routes…" : routeDone.length ? "Check routes again" : `Check ${plural(checkedBefore.length, "route")} for changes`}
            </button>
          </div>
          <div className="nb-note">
            Route checks are worked out on request and not kept by the server. Only the list of sensors passed is kept, on this device.
          </div>
        </>
      )}

      <div className="dim">
        Changes reflect edits to the data sources, which can mean a sensor was installed, removed, or only now mapped.
      </div>
    </section>
  );
}
