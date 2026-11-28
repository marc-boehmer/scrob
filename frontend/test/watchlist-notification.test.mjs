import { test } from "node:test";
import assert from "node:assert/strict";
import { parseWatchlistNotification } from "../src/lib/watchlist-notification.js";

test("parses existing release alerts without changing the date", () => {
  const alert = parseWatchlistNotification("watchlist_release", "Theatrical release date reached: March 1, 2025");
  assert.equal(alert.kind, "release");
  assert.equal(alert.date.toISOString(), "2025-03-01T00:00:00.000Z");
});

test("preserves streaming provider names", () => {
  assert.deepEqual(
    parseWatchlistNotification("watchlist_streaming", "Now available to stream on Netflix, Disney Plus"),
    { kind: "streaming", providers: "Netflix, Disney Plus" },
  );
});

test("leaves unrecognized or invalid messages untouched", () => {
  for (const [type, text] of [
    ["watchlist_release", "Theatrical release date reached: February 30, 2025"],
    ["watchlist_release", "A different announcement"],
    ["watchlist_streaming", "Now available to stream on "],
    ["friend_media_share", "Now available to stream on Netflix"],
  ]) {
    assert.deepEqual(parseWatchlistNotification(type, text), { kind: "unknown", text });
  }
});
