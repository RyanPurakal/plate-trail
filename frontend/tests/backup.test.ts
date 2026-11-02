// Saving routes and areas to a file and adding them back: what the file holds, and how it merges.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { BBox } from "../lib/area";
import type { SavedArea } from "../lib/areas";
import { MAX_AREAS } from "../lib/areas";
import { makeBackup, mergeBackup, mergeSummary, parseBackup, type Backup } from "../lib/backup";
import { MAX_ROUTES, type Pt, type SavedRoute } from "../lib/routes";
import { areaKey, makeSnapshot, routeKey } from "../lib/snapshots";

const box: BBox = [-74.45, 40.49, -74.4, 40.53];
const otherBox: BBox = [-74.6, 40.3, -74.5, 40.4];
const route = (id: string, start: Pt = [-74.4, 40.5], end: Pt = [-74.45, 40.49]): SavedRoute => ({ id, name: `Route ${id}`, start, end, created: "2026-10-22" });
const area = (id: string, bbox: BBox = box): SavedArea => ({ id, name: `Area ${id}`, bbox, created: "2026-10-22" });
const look = (...ids: string[]) => makeSnapshot(ids, {}, "2026-10-22T08:00:00.000Z");
const empty: Backup = { routes: [], areas: [], snapshots: {} };

describe("makeBackup and parseBackup", () => {
  test("a saved file reads back the same routes, areas and their looks", () => {
    const saved: Backup = {
      routes: [route("r1")],
      areas: [area("a1")],
      snapshots: { [routeKey("r1")]: look("osm:1"), [areaKey(box)]: look("osm:2") },
    };
    assert.deepEqual(parseBackup(makeBackup(saved)), saved);
  });

  test("the last change found stays with a look in the file", () => {
    const changed = { found: "2026-10-22T08:00:00.000Z", since: "2026-10-20T08:00:00.000Z", added: ["osm:2"], removed: [] };
    const text = makeBackup({ routes: [], areas: [area("a1")], snapshots: { [areaKey(box)]: { ...look("osm:2"), changed } } });
    assert.deepEqual(parseBackup(text)!.snapshots[areaKey(box)].changed, changed);
  });

  test("looks at boxes that were explored but not saved stay out of the file", () => {
    const text = makeBackup({ routes: [], areas: [area("a1")], snapshots: { [areaKey(box)]: look("osm:2"), [areaKey(otherBox)]: look("osm:3"), [routeKey("gone")]: look("osm:4") } });
    assert.deepEqual(Object.keys(parseBackup(text)!.snapshots), [areaKey(box)]);
  });

  test("anything but this file format is refused", () => {
    for (const raw of ["", "{not json", "[]", "null", "{}", JSON.stringify({ format: "other", version: 1 }), JSON.stringify({ format: "platetrail.backup", version: 2 })]) {
      assert.equal(parseBackup(raw), null, raw);
    }
  });

  test("malformed entries in a file are dropped, and missing lists read as empty", () => {
    const raw = JSON.stringify({
      format: "platetrail.backup", version: 1,
      routes: [route("r1"), { id: "r2", name: "No points" }],
      areas: "nope",
      snapshots: { [routeKey("r1")]: { ids: "nope", seen: "x" } },
    });
    const out = parseBackup(raw)!;
    assert.deepEqual(out.routes.map((r) => r.id), ["r1"]);
    assert.deepEqual(out.areas, []);
    assert.deepEqual(out.snapshots, {});
    assert.deepEqual(parseBackup(JSON.stringify({ format: "platetrail.backup", version: 1 })), empty);
  });
});

describe("mergeBackup", () => {
  test("into an empty browser everything comes across, with its looks", () => {
    const file: Backup = { routes: [route("r1")], areas: [area("a1")], snapshots: { [routeKey("r1")]: look("osm:1"), [areaKey(box)]: look("osm:2") } };
    const m = mergeBackup(empty, file);
    assert.deepEqual([m.routes, m.areas, m.snapshots], [file.routes, file.areas, file.snapshots]);
    assert.equal(mergeSummary(m), "Added 1 route and 1 area.");
  });

  test("items already here are left as they are, keeping their name and newer look", () => {
    const here: Backup = { routes: [{ ...route("mine"), name: "Commute" }], areas: [{ ...area("mine"), name: "Home" }], snapshots: { [areaKey(box)]: look("osm:new"), [routeKey("mine")]: look("osm:new") } };
    const file: Backup = { routes: [route("r1")], areas: [area("a1")], snapshots: { [areaKey(box)]: look("osm:old"), [routeKey("r1")]: look("osm:old") } };
    const m = mergeBackup(here, file);
    assert.deepEqual([m.routes, m.areas, m.snapshots], [here.routes, here.areas, here.snapshots]);
    assert.equal(mergeSummary(m), "Nothing new to add. 2 were already saved here.");
  });

  test("an id already used by a different item gets a new one and leaves that id's route look alone", () => {
    const here: Backup = { routes: [route("x")], areas: [area("x")], snapshots: { [routeKey("x")]: look("osm:mine") } };
    const file: Backup = { routes: [route("x", [-75, 41], [-75.1, 41.1])], areas: [area("x", otherBox)], snapshots: { [routeKey("x")]: look("osm:theirs") } };
    const m = mergeBackup(here, file);
    assert.equal(m.addedRoutes, 1);
    assert.equal(m.addedAreas, 1);
    assert.equal(new Set(m.routes.map((r) => r.id)).size, 2);
    assert.equal(new Set(m.areas.map((a) => a.id)).size, 2);
    assert.deepEqual(m.snapshots, here.snapshots);
  });

  test("items over the limits are counted, not added", () => {
    const here: Backup = {
      routes: Array.from({ length: MAX_ROUTES }, (_, i) => route(`r${i}`, [i, 0], [i, 1])),
      areas: Array.from({ length: MAX_AREAS }, (_, i) => area(`a${i}`, [i, 0, i + 0.1, 0.1])),
      snapshots: {},
    };
    const m = mergeBackup(here, { routes: [route("new", [-75, 41], [-75.1, 41.1])], areas: [area("new", otherBox)], snapshots: {} });
    assert.equal(m.routes.length, MAX_ROUTES);
    assert.equal(m.areas.length, MAX_AREAS);
    assert.equal(mergeSummary(m), `Nothing new to add. 2 did not fit: up to ${MAX_ROUTES} routes and ${MAX_AREAS} areas can be saved.`);
  });
});
