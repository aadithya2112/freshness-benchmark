import { chartSVG } from "../lib/chart.js";
const data = JSON.parse(document.querySelector("#comparison-data").textContent);
const $ = (s) => document.querySelector(s);
const state = { scenario: "nq-100k", operation: "insert", metric: "first" };
const fmt = (v) =>
  v == null
    ? "Unavailable"
    : Number(v).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
const pct = (v) => (v == null ? "Unavailable" : (v * 100).toFixed(1) + "%");
const descriptions = {
  first: [
    "Time until the change is visible",
    "Both a direct read and a search result have shown the requested state. Lower is faster.",
  ],
  confirmed: [
    "Time until repeated confirmation",
    "Each read channel has returned the correct state at least three times over a 50 ms window. Lower is faster.",
  ],
  query: [
    "Query time while changes are running",
    "Real questions search a fixed part of the same changing index. Lower is faster.",
  ],
};
const operations = {
  insert: "A new document becomes present in reads and search.",
  update:
    "The same document ID returns its replacement content and vector, with the new version.",
  delete:
    "A previously retrievable document becomes absent in both read channels.",
};
function readURL() {
  const q = new URLSearchParams(location.search);
  if (Object.hasOwn(data.workloads, q.get("scenario")))
    state.scenario = q.get("scenario");
  if (["insert", "update", "delete"].includes(q.get("operation")))
    state.operation = q.get("operation");
  if (Object.hasOwn(descriptions, q.get("metric")))
    state.metric = q.get("metric");
}
function render() {
  $("#workload").value = state.scenario;
  $("#metric").value = state.metric;
  document
    .querySelectorAll("[data-operation]")
    .forEach((b) =>
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.operation === state.operation),
      ),
    );
  $("#workload-description").textContent =
    data.workloads[state.scenario].description +
    " " +
    operations[state.operation];
  $("#metric-title").textContent = descriptions[state.metric][0];
  $("#metric-explanation").textContent = descriptions[state.metric][1];
  const groups = data.groups.filter(
    (g) => g.scenario === state.scenario && g.operation === state.operation,
  );
  drawGraph(groups);
  const key = state.metric + "_p95",
    ci = state.metric + "_ci",
    max = Math.max(...groups.map((g) => g[key] || 0), 1);
  $("#comparison-list").innerHTML = groups
    .map(
      (g) =>
        `<article class="engine-result" data-engine="${g.backend}"><div class="engine-top"><div><h3>${data.names[g.backend]}</h3><p class="engine-version">Version ${data.versions[g.backend]} · ${g.trials}/${g.expected_trials} trials</p></div><div class="engine-time"><strong>${fmt(g[key])}</strong><span>milliseconds</span></div></div><div class="interval-track" aria-hidden="true"><span style="width:${Math.max(0, ((g[key] || 0) / max) * 100)}%"></span></div><p class="interval-label">95% interval: ${fmt(g[ci][0])}–${fmt(g[ci][1])} ms</p><dl class="engine-facts"><div><dt>Changes confirmed</dt><dd>${pct(g.success_rate)}</dd></div><div><dt>Search recall</dt><dd>${pct(g.ann_recall)}</dd></div><div><dt>Validity checks</dt><dd class="${g.eligible ? "pass" : "limited"}">${g.eligible ? "All passed" : g.failed_runs ? "Setup failed" : "Limits apply"}</dd></div></dl><details><summary>More metrics and individual trials</summary><div class="engine-details">${!g.eligible ? '<p class="notice">This group has incomplete trials or failed validity checks. Inspect its evidence before making a comparison.</p>' : ""}<dl><div><dt>First visible, p95</dt><dd>${fmt(g.first_p95)} ms</dd></div><div><dt>Repeated confirmation, p95</dt><dd>${fmt(g.confirmed_p95)} ms</dd></div><div><dt>Background query, p95</dt><dd>${fmt(g.query_p95)} ms</dd></div><div><dt>Idle query, p95</dt><dd>${fmt(g.idle_query_p95)} ms</dd></div><div><dt>Confirmed within 100 ms</dt><dd>${pct(g.within_100ms)}</dd></div><div><dt>Confirmed within 1 second</dt><dd>${pct(g.within_1000ms)}</dd></div><div><dt>Relevance score (nDCG@10)</dt><dd>${fmt(g.ndcg)}</dd></div><div><dt>Exact-search nDCG@10</dt><dd>${fmt(g.exact_ndcg)}</dd></div><div><dt>Observed regressions</dt><dd>${g.regressions}</dd></div></dl><p class="trial-links">${g.run_ids.map((id) => `<a href="/trials/${id}/">Trial ${data.runs.find((r) => r.run === id)?.trial} →</a>`).join("")}</p></div></details></article>`,
    )
    .join("");
}
function update() {
  const url = new URL(location.href);
  url.search = new URLSearchParams(state).toString();
  history.replaceState(null, "", url);
  render();
  $("#share-status").textContent = "";
}
$("#workload").addEventListener("change", (e) => {
  state.scenario = e.target.value;
  update();
});
$("#metric").addEventListener("change", (e) => {
  state.metric = e.target.value;
  update();
});
document.querySelectorAll("[data-operation]").forEach((b) =>
  b.addEventListener("click", () => {
    state.operation = b.dataset.operation;
    update();
  }),
);
$("#share-comparison").addEventListener("click", async () => {
  update();
  try {
    await navigator.clipboard.writeText(location.href);
    $("#share-status").textContent = "Link copied.";
  } catch {
    $("#share-status").textContent =
      "Copy the address from your browser to share this view.";
  }
});
window.addEventListener("popstate", () => {
  readURL();
  render();
});
readURL();
render();

function drawGraph(groups) {
  const graph = $("#latency-graph");
  graph.innerHTML = chartSVG(
    groups,
    state.metric,
    Math.max(300, graph.clientWidth),
  );
  $("#graph-detail").textContent =
    "Lower bars mean faster observations. Select a bar for its exact values.";
  graph.querySelectorAll("[data-graph-engine]").forEach((bar) => {
    const show = () => {
      const g = groups.find((g) => g.backend === bar.dataset.graphEngine),
        interval = g[state.metric + "_ci"];
      $("#graph-detail").textContent =
        data.names[g.backend] +
        ": " +
        fmt(g[state.metric + "_p95"]) +
        " ms. 95% trial interval: " +
        fmt(interval[0]) +
        "–" +
        fmt(interval[1]) +
        " ms.";
      graph
        .querySelectorAll("[data-graph-engine]")
        .forEach((b) => b.classList.toggle("is-selected", b === bar));
    };
    bar.addEventListener("pointerenter", show);
    bar.addEventListener("focus", show);
    bar.addEventListener("click", show);
    bar.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        show();
      }
    });
  });
}
let graphWidth = 0;
new ResizeObserver((entries) => {
  const width = entries[0].contentRect.width;
  if (Math.abs(width - graphWidth) > 1) {
    graphWidth = width;
    drawGraph(
      data.groups.filter(
        (g) => g.scenario === state.scenario && g.operation === state.operation,
      ),
    );
  }
}).observe($("#latency-graph"));
