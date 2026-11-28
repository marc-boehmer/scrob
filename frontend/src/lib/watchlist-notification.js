const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// Older alerts store English text rather than structured event data.
/**
 * @param {string} type
 * @param {string} text
 * @returns {{kind: "release", date: Date} | {kind: "streaming", providers: string} | {kind: "unknown", text: string}}
 */
export function parseWatchlistNotification(type, text) {
  if (type === "watchlist_release") {
    const match = /^Theatrical release date reached: ([A-Za-z]+) (\d{1,2}), (\d{4})$/.exec(text);
    if (match) {
      const month = MONTHS.indexOf(match[1]);
      const day = Number(match[2]);
      const year = Number(match[3]);
      const date = new Date(Date.UTC(year, month, day));
      if (month >= 0 && date.getUTCFullYear() === year && date.getUTCMonth() === month && date.getUTCDate() === day) {
        return { kind: "release", date };
      }
    }
  }
  const prefix = "Now available to stream on ";
  if (type === "watchlist_streaming" && text.startsWith(prefix) && text.length > prefix.length) {
    return { kind: "streaming", providers: text.slice(prefix.length) };
  }
  return { kind: "unknown", text };
}
