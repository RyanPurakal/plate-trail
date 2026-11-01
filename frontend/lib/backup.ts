// Moving saved routes and areas between browsers as a file the person keeps. The file is made and read
// in the browser; nothing here talks to the API.

import { sameBox, MAX_AREAS, parseAreas, type SavedArea } from "./areas";
import { MAX_ROUTES, newId, parseRoutes, type SavedRoute } from "./routes";
import { areaKey, parseSnapshots, routeKey, type Snapshot } from "./snapshots";

export type Backup = { routes: SavedRoute[]; areas: SavedArea[]; snapshots: Record<string, Snapshot> };

export type Merged = Backup & {
  addedRoutes: number;
  addedAreas: number;
  already: number; // in the file and already saved here
  noRoom: number; // in the file but over the saved-item limits
};

const FORMAT = "platetrail.backup";
const VERSION = 1;
export const MAX_BACKUP_BYTES = 5_000_000;

/** File text for the saved routes and areas, with only their own last looks (not other boxes explored). */
export function makeBackup({ routes, areas, snapshots }: Backup, exported = new Date().toISOString()): string {
  const keys = [...routes.map((r) => routeKey(r.id)), ...areas.map((a) => areaKey(a.bbox))];
  const looks = Object.fromEntries(keys.filter((k) => snapshots[k]).map((k) => [k, snapshots[k]]));
  return JSON.stringify({ format: FORMAT, version: VERSION, exported, routes, areas, snapshots: looks }, null, 2);
}

/** File text -> backup, or null when it is not one of these files. Malformed entries inside are dropped. */
export function parseBackup(raw: string): Backup | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const { format, version, routes, areas, snapshots } = data as Record<string, unknown>;
  if (format !== FORMAT || version !== VERSION) return null;
  return {
    routes: parseRoutes(JSON.stringify(routes ?? [])),
    areas: parseAreas(JSON.stringify(areas ?? [])),
    snapshots: parseSnapshots(JSON.stringify(snapshots ?? {})),
  };
}

const samePt = (a: [number, number], b: [number, number]) => a[0] === b[0] && a[1] === b[1];

/** Adds what the file has and this browser doesn't. Nothing already saved here is changed or removed. */
export function mergeBackup(here: Backup, file: Backup): Merged {
  const routes = [...here.routes];
  const areas = [...here.areas];
  const snapshots = { ...here.snapshots };
  let addedRoutes = 0, addedAreas = 0, already = 0, noRoom = 0;

  for (const r of file.routes) {
    const same = routes.find((x) => samePt(x.start, r.start) && samePt(x.end, r.end));
    if (same) already++;
    else if (routes.length >= MAX_ROUTES) noRoom++;
    else {
      // An id taken by a different route gets a new one, and leaves that id's last look behind.
      const clash = routes.some((x) => x.id === r.id);
      routes.push(clash ? { ...r, id: newId() } : r);
      addedRoutes++;
      const look = file.snapshots[routeKey(r.id)];
      if (look && !clash) snapshots[routeKey(r.id)] = look;
    }
  }
  for (const a of file.areas) {
    if (areas.some((x) => sameBox(x.bbox, a.bbox))) already++;
    else if (areas.length >= MAX_AREAS) noRoom++;
    else {
      areas.push(areas.some((x) => x.id === a.id) ? { ...a, id: newId() } : a);
      addedAreas++;
      // A look this browser already has for the box is newer news than the file's.
      const key = areaKey(a.bbox);
      if (file.snapshots[key] && !snapshots[key]) snapshots[key] = file.snapshots[key];
    }
  }
  return { routes, areas, snapshots, addedRoutes, addedAreas, already, noRoom };
}

const count = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** One plain sentence on what adding a file did. */
export function mergeSummary({ addedRoutes, addedAreas, already, noRoom }: Merged): string {
  const added = [addedRoutes && count(addedRoutes, "route"), addedAreas && count(addedAreas, "area")].filter(Boolean).join(" and ");
  const parts = [added ? `Added ${added}.` : "Nothing new to add."];
  if (already) parts.push(`${already} ${already === 1 ? "was" : "were"} already saved here.`);
  if (noRoom) parts.push(`${noRoom} did not fit: up to ${MAX_ROUTES} routes and ${MAX_AREAS} areas can be saved.`);
  return parts.join(" ");
}
