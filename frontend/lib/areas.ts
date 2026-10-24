// "My areas": map boxes a person wants to look at again, kept only in this browser's localStorage.
// Only the box and a name are stored (no search text); nothing here talks to the API.

import { formatBBox, parseBBox, type BBox } from "./area";
import { cleanName, newId } from "./routes";

export type SavedArea = {
  id: string;
  name: string;
  bbox: BBox; // the snapped box `GET /area` returned
  created: string; // ISO date
};

export const AREAS_KEY = "platetrail.areas.v1";
export const MAX_AREAS = 20;

/** Stored JSON -> areas, dropping anything malformed or repeated. */
export function parseAreas(raw: string | null): SavedArea[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) return [];
  const out: SavedArea[] = [];
  for (const a of data) {
    if (!a || typeof a !== "object") continue;
    const { id, name, bbox, created } = a as Record<string, unknown>;
    const box = Array.isArray(bbox) ? parseBBox(bbox.join(",")) : null;
    if (typeof id !== "string" || typeof name !== "string" || !box) continue;
    if (out.some((x) => x.id === id || sameBox(x.bbox, box))) continue;
    out.push({ id, name: cleanName(name) || "Area", bbox: box, created: typeof created === "string" ? created : "" });
    if (out.length === MAX_AREAS) break;
  }
  return out;
}

export function loadAreas(): SavedArea[] {
  try {
    return parseAreas(window.localStorage.getItem(AREAS_KEY));
  } catch {
    return [];
  }
}

/** Writes the list (removing the key when empty); false if the browser refused. */
export function saveAreas(areas: SavedArea[]): boolean {
  try {
    if (areas.length) window.localStorage.setItem(AREAS_KEY, JSON.stringify(areas));
    else window.localStorage.removeItem(AREAS_KEY);
    return true;
  } catch {
    return false;
  }
}

/** Boxes are compared at the URL's two-decimal precision, the same as their snapshot keys. */
export const sameBox = (a: BBox, b: BBox) => formatBBox(a) === formatBBox(b);

export const findArea = (areas: SavedArea[], bbox: BBox) => areas.find((a) => sameBox(a.bbox, bbox));

/** First "Area N" name not already used. */
export function nextAreaName(areas: SavedArea[]): string {
  const taken = new Set(areas.map((a) => a.name.toLowerCase()));
  let n = areas.length + 1;
  while (taken.has(`area ${n}`)) n++;
  return `Area ${n}`;
}

/** Adds the box unless it is already saved or the list is full. */
export function addArea(areas: SavedArea[], name: string, bbox: BBox): SavedArea[] {
  if (areas.length >= MAX_AREAS || findArea(areas, bbox)) return areas;
  return [...areas, { id: newId(), name: cleanName(name) || nextAreaName(areas), bbox, created: new Date().toISOString() }];
}

export function renameArea(areas: SavedArea[], id: string, name: string): SavedArea[] {
  const n = cleanName(name);
  return n ? areas.map((a) => (a.id === id ? { ...a, name: n } : a)) : areas;
}

export const removeArea = (areas: SavedArea[], id: string) => areas.filter((a) => a.id !== id);
