import { m } from "../../paraglide/messages.js";
import { formatDate, formatNumber } from "../format";
import { formatShortDuration } from "../media-format";

const root = document.getElementById("rewind-content") as HTMLElement | null;
if (root) {
  const userId = root.dataset.userId;
  const year = Number(root.dataset.year);
  const token = root.dataset.token || null;

  const esc = (value: unknown) =>
    String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]!);

  function showError() {
    const error = document.getElementById("rewind-error");
    if (error) {
      error.textContent = root.dataset.errorText || m.stats_rewind_load_failed();
      error.classList.remove("hidden");
    }
  }

  function render(data: any) {
    const summary = document.getElementById("rewind-summary");
    if (summary) {
      const hours = Math.round(data.total_watch_minutes / 60);
      const days = (data.total_watch_minutes / 60 / 24).toFixed(1);
      const watchTime = hours >= 48
        ? m.stats_days_short({ value: formatNumber(Number(days)) })
        : m.stats_hours_short({ value: formatNumber(hours) });
      summary.innerHTML = [
        { value: formatNumber(data.movies_watched), label: m.profile_movies_watched(), color: "text-sky-300" },
        { value: formatNumber(data.shows_watched), label: m.profile_shows_watched(), color: "text-purple-300" },
        { value: formatNumber(data.episodes_watched), label: m.stats_episodes_watched(), color: "text-indigo-300" },
        { value: watchTime, label: m.stats_watch_time(), color: "text-emerald-300" },
      ].map(({ value, label, color }) => `
        <div class="bg-zinc-900/60 border border-zinc-800 rounded-2xl p-5">
          <p class="text-2xl sm:text-3xl font-black ${color} tracking-tight">${esc(value)}</p>
          <p class="text-[11px] text-zinc-500 font-bold uppercase tracking-widest mt-2">${esc(label)}</p>
        </div>
      `).join("");
    }

    const monthData = new Map((data.watch_activity || []).map((item) => [item.month, item]));
    const months = Array.from({ length: 12 }, (_, index) => {
      const key = `${year}-${String(index + 1).padStart(2, "0")}`;
      const item = monthData.get(key) || { movies: 0, episodes: 0 };
      return {
        key,
        label: formatDate(new Date(year, index, 1), { month: "short" }),
        count: item.movies + item.episodes,
      };
    });
    const peak = months.reduce((best, item) => item.count > best.count ? item : best, months[0]);
    const monthContainer = document.getElementById("rewind-months");
    if (monthContainer) {
      if (peak.count === 0) {
        monthContainer.innerHTML = `<p class="text-sm text-zinc-500">${esc(m.stats_rewind_no_history({ year }))}</p>`;
      } else {
        const max = Math.max(...months.map((item) => item.count), 1);
        monthContainer.innerHTML = `
          <p class="text-sm text-zinc-400 mb-4">${esc(m.stats_rewind_busiest_month({ month: peak.label, count: formatNumber(peak.count) }))}</p>
          <div class="h-28 flex items-end gap-1 sm:gap-2">
            ${months.map((item) => {
              const height = item.count ? Math.max(item.count / max * 100, 4) : 0;
              const isPeak = item === peak;
              return `<div class="flex-1 h-full flex flex-col justify-end items-center gap-2" title="${esc(item.label)}: ${formatNumber(item.count)}">
                <div class="w-full rounded-t-sm ${isPeak ? "bg-sky-400" : "bg-zinc-700"}" style="height:${height}%"></div>
                <span class="text-[9px] sm:text-[10px] font-bold text-zinc-500">${esc(item.label)}</span>
              </div>`;
            }).join("")}
          </div>
        `;
      }
    }

    function renderTitles(elementId: string, items: any[], kind: "movie" | "show") {
      const container = document.getElementById(elementId);
      if (!container) return;
      const titles = (items || []).filter((item) => item.title).slice(0, 3);
      if (!titles.length) {
        container.innerHTML = `<p class="col-span-3 text-sm text-zinc-500">${esc(m.stats_rewind_no_history({ year }))}</p>`;
        return;
      }
      container.innerHTML = titles.map((item) => {
        const href = kind === "movie" ? `/media/movie/${encodeURIComponent(item.tmdb_id)}` : `/show/${encodeURIComponent(item.tmdb_id)}`;
        const title = esc(item.title);
        const image = item.poster_path
          ? `<img src="https://image.tmdb.org/t/p/w342${esc(item.poster_path)}" alt="${title}" loading="lazy" class="w-full h-full object-cover">`
          : `<span class="text-xs text-zinc-500 p-2">${title}</span>`;
        return `<a href="${href}" class="group min-w-0">
          <div class="aspect-[2/3] rounded-xl overflow-hidden bg-zinc-800 group-hover:ring-2 group-hover:ring-sky-500/60 transition">${image}</div>
          <p class="text-xs text-zinc-300 font-semibold mt-2 truncate">${title}</p>
          <p class="text-[11px] text-zinc-500 mt-1">${esc(m.stats_plays({ count: item.plays }))}</p>
        </a>`;
      }).join("");
    }
    renderTitles("rewind-movies", data.top_movies, "movie");
    renderTitles("rewind-shows", data.top_shows, "show");

    const genreCounts = new Map<string, number>();
    for (const genre of [...(data.top_movie_genres || []), ...(data.top_show_genres || [])]) {
      genreCounts.set(genre.name, (genreCounts.get(genre.name) || 0) + genre.count);
    }
    const genres = [...genreCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
    const genreContainer = document.getElementById("rewind-genres");
    if (genreContainer) {
      genreContainer.innerHTML = genres.length
        ? genres.map(([name, count]) => `<span class="inline-flex items-center gap-2 bg-zinc-800/70 border border-zinc-700/70 rounded-full px-3 py-1.5 text-xs font-bold text-zinc-300">${esc(name)}<span class="text-sky-300">${formatNumber(count)}</span></span>`).join("")
        : `<p class="text-sm text-zinc-500">${esc(m.stats_no_data())}</p>`;
    }
  }

  async function load() {
    try {
      const params = new URLSearchParams({
        since: `${year}-01-01`,
        until: `${year}-12-31`,
      });
      const res = await fetch(`/api/proxy/profile/${encodeURIComponent(userId || "")}/stats?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        showError();
        return;
      }
      render(await res.json());
    } catch {
      showError();
    }
  }

  load();
}
