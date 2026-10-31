import type { APIRoute } from "astro";
import { api } from "../lib/api";
import { episodeHref } from "../lib/episodeHref";

export const prerender = false;

const pick = <T>(items: T[]): T => items[Math.floor(Math.random() * items.length)];

export const GET: APIRoute = async ({ url, locals, redirect, request }) => {
  const { token } = locals;
  const back = request.headers.get("referer") ?? "/";

  const p = url.searchParams;
  const kind = p.get("kind");
  let href: string | null = null;

  try {
    if (kind === "watchlist") {
      const data = await api.watchlist.list(token);
      const all = [...data.movies, ...data.shows];
      if (all.length) {
        const item = pick(all);
        href = item.type === "series" ? episodeHref(item) : item.tmdb_id ? `/movie/${item.tmdb_id}` : null;
      }
    } else if (kind === "explore-movies" || kind === "explore-shows") {
      const isMovie = kind === "explore-movies";
      const genre = p.getAll("genre");
      const year = p.getAll("year").map(Number).filter((n) => !Number.isNaN(n));
      const collection = p.getAll("collection");
      const watch = p.getAll("watch");
      const arr = p.getAll("arr");
      const langs = p.getAll("lang");
      const inList = p.getAll("in_list");
      const fetchPage = (page: number) =>
        api.media.tmdbList({
          type: isMovie ? "movie" : "series",
          category: p.get("category") ?? "popular",
          page,
          ...(genre.length ? { genre } : {}),
          ...(year.length ? { year } : {}),
          ...(p.get("min_rating") ? { min_rating: Number(p.get("min_rating")) } : {}),
          ...(!isMovie && p.get("status") ? { status: p.get("status")! } : {}),
          ...(collection.length ? { collection } : {}),
          ...(watch.length ? { watch } : {}),
          ...(arr.length ? { arr } : {}),
          ...(langs.length ? { original_language: langs.join("|") } : {}),
          ...(inList.length ? { in_list: inList } : {}),
        }, token);

      const first = await fetchPage(1);
      if (first.total_pages > 0) {
        const page = 1 + Math.floor(Math.random() * first.total_pages);
        const results = (page === 1 ? first : await fetchPage(page)).results.filter((r) => r.tmdb_id);
        if (results.length) {
          const item = pick(results);
          href = isMovie ? `/movie/${item.tmdb_id}` : `/show/${item.tmdb_id}`;
        }
      }
    } else if (kind === "movies" || kind === "shows") {
      const filters = {
        genre: p.getAll("genre"),
        year: p.getAll("year").map(Number).filter((n) => !Number.isNaN(n)),
        watched: p.getAll("watched"),
        ...(p.get("in_list") ? { in_list: p.get("in_list")! } : {}),
      };
      const fetchPage = (page: number) =>
        kind === "movies"
          ? api.media.list({ type: "movie", sort: "title", page, page_size: 1, ...filters }, token)
          : api.shows.list({ sort: "title", page, page_size: 1, status: p.getAll("status"), ...filters }, token);

      // page_size=1 makes the page number a uniform random index into the filtered set
      const first = await fetchPage(1);
      if (first.total_results > 0) {
        const page = 1 + Math.floor(Math.random() * first.total_results);
        const item = (page === 1 ? first : await fetchPage(page)).results[0];
        if (item) {
          href = kind === "movies"
            ? item.tmdb_id ? `/movie/${item.tmdb_id}` : null
            : episodeHref({ ...item, type: "series", season_number: null });
        }
      }
    }
  } catch (e) {
    console.error("Randomizer failed:", e);
  }

  return redirect(href ?? back);
};
