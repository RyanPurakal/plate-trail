// Helpers for the Explore view's box: the `?bbox=w,s,e,n` URL value and the map view -> box step.

export type BBox = [number, number, number, number]; // west, south, east, north

// Matches the API's limit (platetrail.area.MAX_SPAN_DEG); a little under it so outward snapping stays inside.
export const MAX_SPAN_DEG = 0.48;

export function parseBBox(raw: string | null): BBox | null {
  if (!raw) return null;
  const v = raw.split(",").map(Number);
  if (v.length !== 4 || !v.every(Number.isFinite)) return null;
  const [w, s, e, n] = v;
  if (!(-180 <= w && w < e && e <= 180 && -90 <= s && s < n && n <= 90)) return null;
  return [w, s, e, n];
}

export const formatBBox = (b: BBox) => b.map((v) => v.toFixed(2)).join(",");

/** Box spanned by two dragged corners, in either order. */
export function cornersToBBox(a: [number, number], b: [number, number]): BBox {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}

/** The visible map box, shrunk around its centre if it is larger than the API allows. */
export function viewToBBox(b: BBox): { bbox: BBox; shrunk: boolean } {
  const [w, s, e, n] = b;
  const half = MAX_SPAN_DEG / 2;
  const cx = (w + e) / 2;
  const cy = (s + n) / 2;
  const shrunk = e - w > MAX_SPAN_DEG || n - s > MAX_SPAN_DEG;
  const box = [
    Math.max(-180, e - w > MAX_SPAN_DEG ? cx - half : w),
    Math.max(-90, n - s > MAX_SPAN_DEG ? cy - half : s),
    Math.min(180, e - w > MAX_SPAN_DEG ? cx + half : e),
    Math.min(90, n - s > MAX_SPAN_DEG ? cy + half : n),
  ].map((v) => Math.round(v * 1e4) / 1e4) as BBox;
  return { bbox: box, shrunk };
}

/** "2026-10-14T09:12:00Z" -> "Oct 14, 2026" (null-safe). */
export function shortDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];

/** 45 -> "north-east": the nearest of eight compass points for a bearing in degrees. */
export function compassWord(deg: number): string {
  return COMPASS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
}

/** "osm:node/123" -> its page on openstreetmap.org; null for file sensors. */
export function osmUrl(id: string): string | null {
  const m = /^osm:(node|way|relation)\/(\d+)$/.exec(id);
  return m ? `https://www.openstreetmap.org/${m[1]}/${m[2]}` : null;
}

/** Bearings as stored on a map feature: GeoJSON properties may come back as a JSON string. */
export function parseDirections(v: number[] | string | null | undefined): number[] {
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return v ?? [];
}
