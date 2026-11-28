import assert from "node:assert/strict";
import test from "node:test";
import { use24HourTime } from "../src/lib/timeFormat.ts";

test("account time format takes precedence over a missing or stale cookie", () => {
  assert.equal(use24HourTime(true), true);
  assert.equal(use24HourTime(true, "false"), true);
  assert.equal(use24HourTime(false, "true"), false);
});

test("time format falls back to the cookie without account settings", () => {
  assert.equal(use24HourTime(undefined, "true"), true);
  assert.equal(use24HourTime(null, "false"), false);
  assert.equal(use24HourTime(undefined), false);
});
