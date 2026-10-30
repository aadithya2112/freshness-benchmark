const colors = { pgvector: "#2f806b", qdrant: "#386bd6", weaviate: "#b77529" };
const names = { pgvector: "pgvector", qdrant: "Qdrant", weaviate: "Weaviate" };
const number = (value) =>
  Number(value).toLocaleString("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  });

export function chartSVG(groups, metric, width = 720) {
  const height = 320,
    left = 44,
    right = 18,
    top = 35,
    bottom = 251;
  const field = metric + "_p95",
    interval = metric + "_ci";
  const maximum = Math.max(
    1,
    ...groups
      .flatMap((g) => [g[field], ...(g[interval] || [])])
      .filter((v) => v != null),
  );
  const rawStep = (maximum * 1.22) / 4;
  const power = 10 ** Math.floor(Math.log10(rawStep));
  const step =
    [1, 2, 5, 10].map((n) => n * power).find((n) => n >= rawStep) || power * 10;
  const limit = Math.ceil((maximum * 1.22) / step) * step;
  const y = (value) => bottom - (value / limit) * (bottom - top);
  const plotWidth = width - left - right;
  const barWidth = Math.min(76, (plotWidth / groups.length) * 0.48);
  const ticks = Array.from(
    { length: Math.round(limit / step) + 1 },
    (_, i) => i * step,
  );
  const axis = ticks
    .map(
      (t) =>
        `<g><line x1="${left}" x2="${width - right}" y1="${y(t)}" y2="${y(t)}" stroke="${t === 0 ? "#b9c7d8" : "#e8edf3"}"/><text x="${left - 10}" y="${y(t) + 4}" text-anchor="end" fill="#647386" font-size="12">${t.toLocaleString("en-US", { maximumFractionDigits: 2 })}</text></g>`,
    )
    .join("");
  const bars = groups
    .map((g, i) => {
      const x = left + (plotWidth / groups.length) * (i + 0.5),
        value = g[field];
      const [lo, hi] = g[interval] || [];
      const label = value == null ? "Unavailable" : `${number(value)} ms`;
      const detail =
        value == null
          ? `${names[g.backend]}: no successful observations`
          : `${names[g.backend]}: ${label}${lo != null && hi != null ? `, 95% interval ${number(lo)} to ${number(hi)} ms` : ""}`;
      return `<g class="graph-engine" data-graph-engine="${g.backend}" tabindex="0" role="button" aria-label="Show values for ${detail}"><title>${detail}</title>${value != null ? `<rect class="graph-bar" x="${x - barWidth / 2}" y="${y(value)}" width="${barWidth}" height="${bottom - y(value)}" rx="4" fill="${colors[g.backend]}"/>${lo != null && hi != null ? `<line x1="${x}" x2="${x}" y1="${y(hi)}" y2="${y(lo)}" stroke="#1b2b40" stroke-width="2"/><line x1="${x - 7}" x2="${x + 7}" y1="${y(hi)}" y2="${y(hi)}" stroke="#1b2b40" stroke-width="2"/><line x1="${x - 7}" x2="${x + 7}" y1="${y(lo)}" y2="${y(lo)}" stroke="#1b2b40" stroke-width="2"/>` : ""}<text x="${x}" y="${y(Math.max(value, hi ?? value)) - 12}" text-anchor="middle" fill="#20334b" font-size="${width < 420 ? 13 : 15}" font-weight="650">${number(value)}</text>` : `<text x="${x}" y="${bottom - 15}" text-anchor="middle" fill="#647386" font-size="12">Unavailable</text>`}<circle cx="${x - (names[g.backend].length * 7) / 2 - 10}" cy="${bottom + 29}" r="3" fill="${colors[g.backend]}"/><text x="${x}" y="${bottom + 34}" text-anchor="middle" fill="#34455b" font-size="13">${names[g.backend]}</text></g>`;
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="group" aria-label="Latency comparison in milliseconds. Lower bars are faster. Whiskers show 95% bootstrap intervals over trials."><text x="${left}" y="15" fill="#647386" font-size="12">Milliseconds</text>${axis}${bars}</svg>`;
}
