// On-device storage helpers: what a stored value turns back into, and how looks are compared and pruned.

import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";

import type { BBox } from "../lib/area";
import { addArea, MAX_AREAS, nextAreaName, parseAreas, renameArea, saveAreas, loadAreas, AREAS_KEY } from "../lib/areas";
import { addRoute, cleanName, MAX_NAME, MAX_ROUTES, nextRouteName, parseRoutes, removeRoute, renameRoute } from "../lib/routes";
import {
  areaKey, diffSnapshot, forgetLooks, loadSnapshots, makeSnapshot, MAX_AREA_SNAPSHOTS, parseSnapshots, putSnapshot, recordLook, routeKey,
  SNAP_KEY, type Snapshot,
} from "../lib/snapshots";

// A Map-backed stand-in for the browser's localStorage.
class MemoryStorage {
  items = new Map<string, string>();
  getItem(k: string) { return this.items.get(k) ?? null; }
  setItem(k: string, v: string) { this.items.set(k, String(v)); }
  removeItem(k: string) { this.items.delete(k); }
}

let store: MemoryStorage;
beforeEach(() => {
  store = new MemoryStorage();
  (globalThis as { window?: unknown }).window = { localStorage: store };
});

// Loosely typed on purpose: tests feed parseRoutes values a hand-edited store might hold.
const route = (over: Record<string, unknown> = {}) => ({ id: "r1", name: "Commute", start: [-74.4, 40.5], end: [-74.45, 40.49], created: "2026-10-22", ...over });

describe("routes", () => {
  test("parseRoutes survives missing, broken and non-list values", () => {
    assert.deepEqual(parseRoutes(null), []);
    assert.deepEqual(parseRoutes("{not json"), []);
    assert.deepEqual(parseRoutes(JSON.stringify({ id: "r1" })), []);
  });

  test("parseRoutes drops malformed and repeated entries, rounds points and tidies names", () => {
    const raw = JSON.stringify([
      route({ name: "  Morning\n  drive ", start: [-74.412345, 40.512345] }),
      route({ name: "Same id again" }),
      route({ id: "r2", start: [200, 40] }),
      route({ id: "r3", end: "nowhere" }),
      { id: 4, name: "Number id", start: [0, 0], end: [1, 1] },
      route({ id: "r5", name: "   ", created: undefined }),
      null,
    ]);
    const out = parseRoutes(raw);
    assert.deepEqual(out.map((r) => r.id), ["r1", "r5"]);
    assert.equal(out[0].name, "Morning drive");
    assert.deepEqual(out[0].start, [-74.4123, 40.5123]);
    assert.equal(out[1].name, "Route");
    assert.equal(out[1].created, "");
  });

  test("parseRoutes keeps at most MAX_ROUTES", () => {
    const raw = JSON.stringify(Array.from({ length: MAX_ROUTES + 5 }, (_, i) => route({ id: `r${i}` })));
    assert.equal(parseRoutes(raw).length, MAX_ROUTES);
  });

  test("names are trimmed to MAX_NAME and default to the first free Route N", () => {
    assert.equal(cleanName("x".repeat(MAX_NAME + 10)).length, MAX_NAME);
    const routes = parseRoutes(JSON.stringify([route({ name: "Route 2" })]));
    assert.equal(nextRouteName(routes), "Route 3");
    const added = addRoute(routes, "  ", [-74.400001, 40.5], [-74.41, 40.51]);
    assert.equal(added.length, 2);
    assert.equal(added[1].name, "Route 3");
    assert.deepEqual(added[1].start, [-74.4, 40.5]);
  });

  test("add stops at the limit; rename ignores blank names; remove by id", () => {
    const full = parseRoutes(JSON.stringify(Array.from({ length: MAX_ROUTES }, (_, i) => route({ id: `r${i}` }))));
    assert.equal(addRoute(full, "One more", [0, 0], [1, 1]), full);
    const routes = parseRoutes(JSON.stringify([route()]));
    assert.equal(renameRoute(routes, "r1", "   "), routes);
    assert.equal(renameRoute(routes, "r1", "School run")[0].name, "School run");
    assert.deepEqual(removeRoute(routes, "r1"), []);
  });
});

describe("areas", () => {
  const box: BBox = [-74.45, 40.48, -74.35, 40.55];

  test("parseAreas drops invalid boxes and repeats of the same box", () => {
    const raw = JSON.stringify([
      { id: "a1", name: "Edison", bbox: box, created: "2026-10-23" },
      { id: "a2", name: "Same box", bbox: [-74.4500001, 40.48, -74.35, 40.55] },
      { id: "a3", name: "Flipped", bbox: [-74.35, 40.48, -74.45, 40.55] },
      { id: "a4", name: "Short", bbox: [1, 2, 3] },
      { id: "a1", name: "Same id", bbox: [-74.2, 40.4, -74.1, 40.5] },
    ]);
    assert.deepEqual(parseAreas(raw).map((a) => a.id), ["a1"]);
  });

  test("addArea skips a saved box and a full list; names default to Area N", () => {
    const one = addArea([], "", box);
    assert.equal(one[0].name, "Area 1");
    assert.equal(addArea(one, "Again", box), one);
    assert.equal(nextAreaName(renameArea(one, one[0].id, "Area 2")), "Area 3");
    let many = one;
    for (let i = 1; many.length < MAX_AREAS; i++) many = addArea(many, "", [i, 0, i + 0.1, 0.1]);
    assert.equal(addArea(many, "", [-10, 0, -9.9, 0.1]), many);
  });

  test("save and load round-trip through localStorage; an empty list removes the key", () => {
    const areas = addArea([], "Home area", box);
    assert.equal(saveAreas(areas), true);
    assert.deepEqual(loadAreas(), areas);
    saveAreas([]);
    assert.equal(store.getItem(AREAS_KEY), null);
  });

  test("blocked storage reads as empty and a refused write returns false", () => {
    (globalThis as { window?: unknown }).window = {
      get localStorage(): never { throw new Error("blocked"); },
    };
    assert.deepEqual(loadAreas(), []);
    assert.equal(saveAreas(addArea([], "x", box)), false);
  });
});

describe("snapshots", () => {
  const snap = (ids: string[], sources: Record<string, string | null> = {}, seen = "2026-10-20T00:00:00Z") => makeSnapshot(ids, sources, seen);

  test("makeSnapshot sorts and dedupes ids and drops sources without a date", () => {
    const s = snap(["b", "a", "b"], { osm: "2026-10-01", file: null });
    assert.deepEqual(s.ids, ["a", "b"]);
    assert.deepEqual(s.sources, { osm: "2026-10-01" });
  });

  test("diffSnapshot lists added, removed and updated sources; null on a first look", () => {
    const before = snap(["a", "b"], { osm: "2026-10-01", file: "2026-09-01" });
    const now = snap(["b", "c"], { osm: "2026-10-15", file: "2026-09-01", extra: "2026-10-15" }, "2026-10-29T00:00:00Z");
    assert.equal(diffSnapshot(undefined, now), null);
    assert.deepEqual(diffSnapshot(before, now), { since: before.seen, added: ["c"], removed: ["a"], updated: ["osm"] });
  });

  test("parseSnapshots keeps only area/route keys with string id lists", () => {
    const raw = JSON.stringify({
      "area:1.00,2.00,3.00,4.00": { ids: ["x"], sources: { osm: "2026-10-01" }, seen: "2026-10-20" },
      "route:r1": { ids: ["y"], sources: ["not", "an", "object"], seen: "2026-10-21" },
      "route:r2": { ids: [1, 2], seen: "2026-10-21" },
      "route:r3": { ids: [], sources: {} },
      other: { ids: [], sources: {}, seen: "2026-10-21" },
    });
    const out = parseSnapshots(raw);
    assert.deepEqual(Object.keys(out).sort(), ["area:1.00,2.00,3.00,4.00", "route:r1"]);
    assert.deepEqual(out["route:r1"].sources, {});
    assert.deepEqual(parseSnapshots("[]"), {});
  });

  test("putSnapshot keeps the newest areas, plus pinned ones and every route", () => {
    let all: Record<string, Snapshot> = { [routeKey("r1")]: snap(["y"], {}, "2020-01-01T00:00:00Z") };
    const pinned = areaKey([0, 0, 0.1, 0.1]);
    all = putSnapshot(all, pinned, snap([], {}, "2020-01-01T00:00:00Z"));
    for (let i = 1; i <= MAX_AREA_SNAPSHOTS + 3; i++) {
      const seen = `2026-10-${String(i).padStart(2, "0")}T00:00:00Z`;
      all = putSnapshot(all, areaKey([i, 0, i + 0.1, 0.1]), snap([`s${i}`], {}, seen), new Set([pinned]));
    }
    const areas = Object.keys(all).filter((k) => k.startsWith("area:"));
    assert.equal(areas.length, MAX_AREA_SNAPSHOTS + 1);
    assert.ok(pinned in all);
    assert.ok(routeKey("r1") in all);
    assert.ok(!(areaKey([1, 0, 1.1, 0.1]) in all), "oldest unpinned area is dropped");
  });

  test("recordLook returns the change from the stored look and replaces it", () => {
    const key = routeKey("r1");
    assert.equal(recordLook(key, snap(["a"])), null);
    const change = recordLook(key, snap(["a", "b"], {}, "2026-10-29T00:00:00Z"));
    assert.deepEqual(change?.added, ["b"]);
    assert.deepEqual(loadSnapshots()[key].ids, ["a", "b"]);
    assert.deepEqual(recordLook(key, snap(["a", "b"], {}, "2026-10-30T00:00:00Z"))?.added, []);
  });

  test("forgetLooks removes matching keys and clears storage when nothing is left", () => {
    recordLook(areaKey([0, 0, 0.1, 0.1]), snap(["a"]));
    recordLook(routeKey("r1"), snap(["b"]));
    forgetLooks((k) => k.startsWith("area:"));
    assert.deepEqual(Object.keys(loadSnapshots()), [routeKey("r1")]);
    forgetLooks(() => true);
    assert.equal(store.getItem(SNAP_KEY), null);
  });
});
