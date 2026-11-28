import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

const pages = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/pages");

test("movie details offer sharing for signed-in and signed-out visitors, but not episodes", async () => {
  const source = await readFile(path.join(pages, "media/[type]/[id].astro"), "utf8");
  assert.match(source, /\{isMovie && \(\s*<ShareMedia\s+title=\{item\.title\}\s+mediaType="movie"\s+tmdbId=\{item\.tmdb_id\}\s+href=\{`\/movie\/\$\{item\.tmdb_id\}`\}\s+authenticated=\{!!user\}\s*\/>\s*\)\}/);
});

for (const [page, href] of [
  ["show/[id].astro", /href=\{`\/show\/\$\{show\.tmdb_id\}`\}/],
  ["show/tvdb/[id].astro", /href=\{show\.tmdb_id_cross \? `\/show\/\$\{show\.tmdb_id_cross\}` : `\/show\/tvdb\/\$\{show\.tvdb_id\}`\}/],
]) {
  test(`${page} keeps show sharing available to all visitors`, async () => {
    const source = await readFile(path.join(pages, page), "utf8");
    const share = source.match(/<ShareMedia\b[\s\S]*?\/>/)?.[0];
    assert.ok(share);
    assert.match(share, /mediaType="series"/);
    assert.match(share, href);
    assert.match(share, /authenticated=\{!!user\}/);
  });
}
