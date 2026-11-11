// Last-seen sensor lists for explored areas and checked routes, kept only in this browser's localStorage,
// so a later look can say what changed. Holds sensor ids and data dates; routes are referenced by id only.

import type { AreaResult } from "./api";
import { formatBBox, type BBox } from "./area";

export type Snapshot = {
  ids: string[]; // sensor ids, sorted
  sources: Record<string, string>; // source id -> data date (latest OSM edit, or a file's modified time)
  seen: string; // ISO time of the look
  changed?: FoundChange; // the last sensor change a look found, kept so it can still be shown after that look
};

export type SnapshotChange = {
  since: string; // when the previous look was
  added: string[];
  removed: string[];
  updated: string[]; // source ids whose data date moved on
  earlier?: FoundChange; // when this look found no sensor change: the last one an earlier look found
};

export type FoundChange = {
  found: string; // when the look that found it was
  since: string; // the look before that one
  added: string[];
  removed: string[];
};

export const SNAP_KEY = "platetrail.snapshots.v1";
export const MAX_AREA_SNAPSHOTS = 10;
export const KEEP_CHANGE_DAYS = 30;
const MAX_IDS = 5000;

export const areaKey = (bbox: BBox) => `area:${formatBBox(bbox)}`;
export const routeKey = (id: string) => `route:${id}`;

const isKey = (k: string) => /^(area|route):/.test(k);

export function makeSnapshot(ids: Iterable<string>, sources: Record<string, string | null> = {}, seen = new Date().toISOString()): Snapshot {
  const clean = Object.fromEntries(Object.entries(sources).filter((e): e is [string, string] => typeof e[1] === "string"));
  return { ids: [...new Set(ids)].sort().slice(0, MAX_IDS), sources: clean, seen };
}

/** The look stored for a `GET /area` result: its sensor ids and each source's data date. */
export const areaSnapshot = (a: AreaResult) => makeSnapshot(
  a.sensors.features.map((f) => f.properties.id),
  Object.fromEntries(a.summary.sources.map((src) => [src.id, src.id === "osm" ? src.latest_edit : src.fetched_at])),
);

const isIds = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

function parseFound(v: unknown): FoundChange | null {
  if (!v || typeof v !== "object") return null;
  const { found, since, added, removed } = v as Record<string, unknown>;
  if (typeof found !== "string" || typeof since !== "string" || !isIds(added) || !isIds(removed)) return null;
  return { found, since, added: added.slice(0, MAX_IDS), removed: removed.slice(0, MAX_IDS) };
}

/** Stored JSON -> snapshots by key, dropping anything malformed. */
export function parseSnapshots(raw: string | null): Record<string, Snapshot> {
  if (!raw) return {};
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return {};
  const out: Record<string, Snapshot> = {};
  for (const [k, v] of Object.entries(data)) {
    if (!isKey(k) || !v || typeof v !== "object") continue;
    const { ids, sources, seen, changed } = v as Record<string, unknown>;
    if (!isIds(ids) || typeof seen !== "string") continue;
    const src = sources && typeof sources === "object" && !Array.isArray(sources) ? (sources as Record<string, string | null>) : {};
    out[k] = makeSnapshot(ids, src, seen);
    const found = parseFound(changed);
    if (found) out[k].changed = found;
  }
  return out;
}

export function loadSnapshots(): Record<string, Snapshot> {
  try {
    return parseSnapshots(window.localStorage.getItem(SNAP_KEY));
  } catch {
    return {};
  }
}

export function saveSnapshots(all: Record<string, Snapshot>): boolean {
  try {
    if (Object.keys(all).length) window.localStorage.setItem(SNAP_KEY, JSON.stringify(all));
    else window.localStorage.removeItem(SNAP_KEY);
    return true;
  } catch {
    return false;
  }
}

/** What differs between a previous look and the current one; null when there was no previous look. */
export function diffSnapshot(prev: Snapshot | undefined, now: Snapshot): SnapshotChange | null {
  if (!prev) return null;
  const before = new Set(prev.ids);
  const after = new Set(now.ids);
  return {
    since: prev.seen,
    added: now.ids.filter((id) => !before.has(id)),
    removed: prev.ids.filter((id) => !after.has(id)),
    updated: Object.keys(now.sources).filter((s) => prev.sources[s] && prev.sources[s] !== now.sources[s]),
  };
}

/** The last sensor change found for this look, unless it was found more than KEEP_CHANGE_DAYS ago. */
export function latestChange(snap: Snapshot | undefined, now = Date.now()): FoundChange | null {
  const c = snap?.changed;
  return c && now - new Date(c.found).getTime() <= KEEP_CHANGE_DAYS * 86_400_000 ? c : null;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "2 sensors newly listed, 1 no longer listed". */
export function sensorChangeText(c: Pick<SnapshotChange, "added" | "removed">): string {
  const parts = [
    c.added.length > 0 && `${plural(c.added.length, "sensor")} newly listed`,
    c.removed.length > 0 && `${c.removed.length} no longer listed`,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : "no sensors added or removed";
}

/** Stores `snap` under `key`, keeping only the most recently seen MAX_AREA_SNAPSHOTS areas
 *  besides the `pinned` ones (saved areas, which are kept however long ago they were seen). */
export function putSnapshot(all: Record<string, Snapshot>, key: string, snap: Snapshot, pinned: ReadonlySet<string> = new Set()): Record<string, Snapshot> {
  const next = { ...all, [key]: snap };
  const areas = Object.keys(next).filter((k) => k.startsWith("area:") && !pinned.has(k)).sort((a, b) => next[b].seen.localeCompare(next[a].seen));
  for (const k of areas.slice(MAX_AREA_SNAPSHOTS)) delete next[k];
  return next;
}

/** Drops snapshots whose key matches; used when routes are deleted or areas are forgotten. */
export const dropSnapshots = (all: Record<string, Snapshot>, keep: (key: string) => boolean) =>
  Object.fromEntries(Object.entries(all).filter(([k]) => keep(k)));

/** Compare with the stored look for `key`, then store the new one. Returns the change (null on a first look).
 *  A sensor change stays with the stored look, so a reload or a second look can still say what it was. */
export function recordLook(key: string, snap: Snapshot, pinned?: ReadonlySet<string>): SnapshotChange | null {
  const all = loadSnapshots();
  const change = diffSnapshot(all[key], snap);
  if (change && (change.added.length || change.removed.length)) {
    const { since, added, removed } = change;
    saveSnapshots(putSnapshot(all, key, { ...snap, changed: { found: snap.seen, since, added, removed } }, pinned));
    return change;
  }
  const earlier = latestChange(all[key], new Date(snap.seen).getTime());
  saveSnapshots(putSnapshot(all, key, earlier ? { ...snap, changed: earlier } : snap, pinned));
  return change && earlier ? { ...change, earlier } : change;
}

/** When each item was last looked at from this browser (ISO time), or null if never; for the My areas / My routes lists. */
export function lastLooks<T extends { id: string }>(items: readonly T[], key: (item: T) => string, all: Record<string, Snapshot> = loadSnapshots()): Record<string, string | null> {
  return Object.fromEntries(items.map((it) => [it.id, all[key(it)]?.seen ?? null]));
}

/** Remove stored looks matching `drop` from this browser. */
export function forgetLooks(drop: (key: string) => boolean) {
  saveSnapshots(dropSnapshots(loadSnapshots(), (k) => !drop(k)));
}
