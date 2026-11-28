import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

const english = JSON.parse(readFileSync(new URL("../messages/en.json", import.meta.url), "utf8"));
const german = JSON.parse(readFileSync(new URL("../messages/de.json", import.meta.url), "utf8"));
const tokens = (text, pattern) => [...text.matchAll(pattern)].map((match) => match[0]).sort();

function checkMessage(source, translation, path) {
  if (typeof source === "string") {
    assert.equal(typeof translation, "string", path);
    assert.deepEqual(tokens(translation, /\{[a-zA-Z_]\w*\}/g), tokens(source, /\{[a-zA-Z_]\w*\}/g), path);
    assert.deepEqual(tokens(translation, /<[^>]+>/g), tokens(source, /<[^>]+>/g), path);
    assert.doesNotMatch(translation, /__\s*PH\d+\s*__/i, path);
    return;
  }
  if (Array.isArray(source)) {
    assert.ok(Array.isArray(translation), path);
    assert.equal(translation.length, source.length, path);
    source.forEach((value, i) => checkMessage(value, translation[i], `${path}[${i}]`));
    return;
  }
  assert.ok(translation && typeof translation === "object", path);
  assert.deepEqual(Object.keys(translation).sort(), Object.keys(source).sort(), path);
  for (const key of Object.keys(source)) {
    if (key === "declarations" || key === "selectors") {
      assert.deepEqual(translation[key], source[key], `${path}.${key}`);
    } else {
      checkMessage(source[key], translation[key], `${path}.${key}`);
    }
  }
}

test("German messages preserve English catalog structure, placeholders and markup", () => {
  assert.deepEqual(Object.keys(german).sort(), Object.keys(english).sort());
  for (const key of Object.keys(english)) checkMessage(english[key], german[key], key);
});

test("key actions use their intended meaning in German", () => {
  assert.equal(german.common_save, "Speichern");
  assert.equal(german.auth_sign_in, "Anmelden");
  assert.equal(german.profile_settings_bio, "Über mich");
  assert.equal(german.media_trailer, "Trailer");
  assert.equal(german.castcrew_cast, "Besetzung");
  assert.equal(german.genre_action, "Action");
});

test("watch details and history use contextual German terminology", () => {
  assert.equal(german.watch_stats_play_one, "{count} Wiedergabe");
  assert.equal(german.watch_stats_play_other, "{count} Wiedergaben");
  assert.equal(german.watch_stats_watched, "{time} angesehen");
  assert.equal(german.watch_stats_last_watched, "Zuletzt angesehen am {date}");
  assert.equal(german.watch_stats_days, "{days} Tage");
  assert.equal(german.watch_source_manual, "Manuell");
  assert.equal(german.watch_source_import, "Import");
  assert.equal(german.history_total_watch_time, "Gesamte Wiedergabedauer");
  assert.equal(german.media_watched_on, "Gesehen am {date}");
});
