// Trying failed area checks again on a return visit: only the retried entries change.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { replaceById } from "../lib/visits";

describe("replaceById", () => {
  const prev = [{ id: "a", status: "done" }, { id: "b", status: "error" }, { id: "c", status: "error" }];

  test("retried entries replace the old ones in place", () => {
    assert.deepEqual(replaceById(prev, [{ id: "c", status: "first" }]),
      [{ id: "a", status: "done" }, { id: "b", status: "error" }, { id: "c", status: "first" }]);
  });

  test("an id not in the earlier list is not added", () => {
    assert.deepEqual(replaceById(prev, [{ id: "z", status: "done" }]), prev);
  });
});
