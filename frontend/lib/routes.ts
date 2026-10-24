// "My routes": routes a person drives, kept only in this browser's localStorage. Nothing here talks to the API.

export type Pt = [number, number]; // lon, lat

export type SavedRoute = {
  id: string;
  name: string;
  start: Pt;
  end: Pt;
  created: string; // ISO date
};

export const STORAGE_KEY = "platetrail.routes.v1";
export const MAX_ROUTES = 20;
export const MAX_NAME = 60;

// Four decimals is about 10 m: plenty for picking a road, no finer than needed.
const roundPt = ([lon, lat]: Pt): Pt => [Math.round(lon * 1e4) / 1e4, Math.round(lat * 1e4) / 1e4];

const isPt = (v: unknown): v is Pt =>
  Array.isArray(v) && v.length === 2 && v.every(Number.isFinite) &&
  Math.abs(v[0]) <= 180 && Math.abs(v[1]) <= 90;

export const cleanName = (name: string) => name.replace(/\s+/g, " ").trim().slice(0, MAX_NAME);

/** Stored JSON -> routes, dropping anything malformed (a hand-edited or older value never breaks the page). */
export function parseRoutes(raw: string | null): SavedRoute[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) return [];
  const out: SavedRoute[] = [];
  for (const r of data) {
    if (!r || typeof r !== "object") continue;
    const { id, name, start, end, created } = r as Record<string, unknown>;
    if (typeof id !== "string" || typeof name !== "string" || !isPt(start) || !isPt(end)) continue;
    if (out.some((x) => x.id === id)) continue;
    out.push({
      id, name: cleanName(name) || "Route", start: roundPt(start), end: roundPt(end),
      created: typeof created === "string" ? created : "",
    });
    if (out.length === MAX_ROUTES) break;
  }
  return out;
}

/** Saved routes, or [] when storage is empty or blocked. */
export function loadRoutes(): SavedRoute[] {
  try {
    return parseRoutes(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return [];
  }
}

/** Writes the list (removing the key when empty); false if the browser refused. */
export function saveRoutes(routes: SavedRoute[]): boolean {
  try {
    if (routes.length) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(routes));
    else window.localStorage.removeItem(STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

/** First "Route N" name not already used. */
export function nextRouteName(routes: SavedRoute[]): string {
  const taken = new Set(routes.map((r) => r.name.toLowerCase()));
  let n = routes.length + 1;
  while (taken.has(`route ${n}`)) n++;
  return `Route ${n}`;
}

/** Random id for an item kept in this browser. */
export const newId = () => typeof crypto !== "undefined" && "randomUUID" in crypto
  ? crypto.randomUUID()
  : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export function addRoute(routes: SavedRoute[], name: string, start: Pt, end: Pt): SavedRoute[] {
  if (routes.length >= MAX_ROUTES) return routes;
  return [...routes, {
    id: newId(), name: cleanName(name) || nextRouteName(routes), start: roundPt(start), end: roundPt(end),
    created: new Date().toISOString(),
  }];
}

export function renameRoute(routes: SavedRoute[], id: string, name: string): SavedRoute[] {
  const n = cleanName(name);
  return n ? routes.map((r) => (r.id === id ? { ...r, name: n } : r)) : routes;
}

export const removeRoute = (routes: SavedRoute[], id: string) => routes.filter((r) => r.id !== id);

/** Straight-line distance in km (haversine), shown as a rough size until routing lands. */
export function straightKm([lon1, lat1]: Pt, [lon2, lat2]: Pt): number {
  const rad = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}
