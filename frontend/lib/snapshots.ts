// Last-seen sensor lists for explored areas and checked routes, kept only in this browser's localStorage,
// so a later look can say what changed. Holds sensor ids and data dates; routes are referenced by id only.

import { formatBBox, type BBox } from "./area";

export type Snapshot = {
  ids: string[]; // sensor ids, sorted
  sources: Record<string, string>; // source id -> data date (latest OSM edit, or a file's modified time)
  seen: string; // ISO time of the look
};

export type SnapshotChange = {
  since: string; // when the previous look was
  added: string[];
  removed: string[];
  updated: string[]; // source ids whose data date moved on
};

export const SNAP_KEY = "platetrail.snapshots.v1";
export const MAX_AREA_SNAPSHOTS = 10;
const MAX_IDS = 5000;

export const areaKey = (bbox: BBox) => `area:${formatBBox(bbox)}`;
export const routeKey = (id: string) => `route:${id}`;

const isKey = (k: string) => /^(area|route):/.test(k);

export function makeSnapshot(ids: Iterable<string>, sources: Record<string, string | null> = {}, seen = new Date().toISOString()): Snapshot {
  const clean = Object.fromEntries(Object.entries(sources).filter((e): e is [string, string] => typeof e[1] === "string"));
  return { ids: [...new Set(ids)].sort().slice(0, MAX_IDS), sources: clean, seen };
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
    const { ids, sources, seen } = v as Record<string, unknown>;
    if (!Array.isArray(ids) || !ids.every((x) => typeof x === "string") || typeof seen !== "string") continue;
    const src = sources && typeof sources === "object" && !Array.isArray(sources) ? (sources as Record<string, string | null>) : {};
    out[k] = makeSnapshot(ids as string[], src, seen);
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

/** Compare with the stored look for `key`, then store the new one. Returns the change (null on a first look). */
export function recordLook(key: string, snap: Snapshot, pinned?: ReadonlySet<string>): SnapshotChange | null {
  const all = loadSnapshots();
  const change = diffSnapshot(all[key], snap);
  saveSnapshots(putSnapshot(all, key, snap, pinned));
  return change;
}

/** Remove stored looks matching `drop` from this browser. */
export function forgetLooks(drop: (key: string) => boolean) {
  saveSnapshots(dropSnapshots(loadSnapshots(), (k) => !drop(k)));
}
