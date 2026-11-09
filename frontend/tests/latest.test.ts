// Overlapping area loads: only the newest request may update the page.

import assert from "node:assert/strict";
import { test } from "node:test";

import { latestOnly } from "../lib/latest";

test("only the most recent ticket is current", () => {
  const l = latestOnly();
  const a = l.start();
  assert.ok(l.isCurrent(a));
  const b = l.start();
  assert.ok(!l.isCurrent(a));
  assert.ok(l.isCurrent(b));
});

test("a slow first answer arriving last does not replace the second", async () => {
  const l = latestOnly();
  let shown: string | null = null;
  const load = async (name: string, ms: number) => {
    const t = l.start();
    await new Promise((r) => setTimeout(r, ms));
    if (l.isCurrent(t)) shown = name;
  };
  await Promise.all([load("first", 30), load("second", 5)]);
  assert.equal(shown, "second");
});

test("separate trackers do not interfere", () => {
  const x = latestOnly();
  const y = latestOnly();
  const tx = x.start();
  y.start();
  y.start();
  assert.ok(x.isCurrent(tx));
});
