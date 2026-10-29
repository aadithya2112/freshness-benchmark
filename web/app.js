"use strict";
let DATA = null;
const state = {
  page: "results",
  scenario: "nq-100k",
  operation: "insert",
  metric: "first",
  expanded: false,
};
const names = { qdrant: "Qdrant", weaviate: "Weaviate", pgvector: "pgvector" };
const labels = {
  "scifact-small": "SciFact · 4,000 documents",
  "nq-10k": "Natural Questions · 10,000 documents",
  "nq-100k": "Natural Questions · 100,000 documents",
  "nq-100k-burst": "Natural Questions · 100,000 documents · burst",
};
const scenarios = Object.keys(labels);
const $ = (s) => document.querySelector(s);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (value) =>
  value == null
    ? "—"
    : Number(value).toLocaleString(undefined, {
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      });
const pct = (value) => (value == null ? "—" : (value * 100).toFixed(1) + "%");
const ms = (value) => (value == null ? "—" : num(value) + " ms");
const toast = (message) => {
  const t = $("#toast");
  t.textContent = message;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
};
function hashState() {
  const [page, query = ""] = (location.hash.slice(1) || "results").split("?");
  const params = new URLSearchParams(query);
  state.page = ["results", "methodology", "datasets", "reproduce"].includes(
    page,
  )
    ? page
    : "results";
  if (scenarios.includes(params.get("scenario")))
    state.scenario = params.get("scenario");
  if (["insert", "update", "delete"].includes(params.get("operation")))
    state.operation = params.get("operation");
  if (["first", "confirmed", "query"].includes(params.get("metric")))
    state.metric = params.get("metric");
  render();
}
function changeHash() {
  location.hash =
    "results?" +
    new URLSearchParams({
      scenario: state.scenario,
      operation: state.operation,
      metric: state.metric,
    });
}
function version(backend) {
  return (
    DATA.runs.find((r) => r.backend === backend && r.summary)?.summary.metadata
      .backend_before.version || ""
  );
}
function resources(backend) {
  const c = DATA.experiment.containers.find(c => c.name.endsWith('-' + backend));
  return c ? `${c.cpu_quota / 1e9} CPUs / ${c.memory_bytes / 2 ** 30} GiB` : 'Resource limits not recorded';
}
function selectedGroups() {
  return DATA.groups
    .filter(
      (g) => g.scenario === state.scenario && g.operation === state.operation,
    )
    .sort((a, b) => a.backend.localeCompare(b.backend));
}
function setPage() {
  document
    .querySelectorAll(".page")
    .forEach((p) => (p.hidden = p.id !== "page-" + state.page));
  document.querySelectorAll("nav a").forEach((a) => {
    if (a.dataset.page === state.page) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title =
    {
      results: "Results",
      methodology: "Methodology",
      datasets: "Datasets",
      reproduce: "Reproduce",
    }[state.page] + " — Freshness Benchmark";
}
function render() {
  setPage();
  if (!DATA) return;
  $("#scenario").value = state.scenario;
  $("#metric").value = state.metric;
  document
    .querySelectorAll("[data-op]")
    .forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.op === state.operation)),
    );
  const groups = selectedGroups();
  renderChart(groups);
  renderTable(groups);
  renderRuns();
  renderCalibration();
  renderDatasets();
  const args = DATA.experiment.arguments;
  $("#run-status").textContent =
    (DATA.track === "pilot" ? "Pilot · " : "") +
    (DATA.status === "complete"
      ? `${DATA.completed}/${DATA.planned} completed trials${DATA.failed ? ` · ${DATA.failed} setup failure(s)` : ""} · ${Object.keys(DATA.experiment.datasets).length} dataset(s)`
      : `Experiment in progress · ${DATA.completed}/${DATA.planned} trials complete`);
  $("#scope-line").textContent =
    `${args.duration}s per trial · ${args.trials} trials per cell`;
  $("#hardware-line").textContent =
    `${DATA.experiment.host.cpu_model || DATA.experiment.host.platform} · ${DATA.experiment.docker_host?.OperatingSystem || "Docker"} · ${resources('qdrant')} per engine`;
  const interrupted = (DATA.continuations || []).filter(c => c.interrupted_attempt).length;
  $("#continuation-note").hidden = !interrupted;
  $("#continuation-note").textContent = interrupted ? `${interrupted} interrupted attempt retained separately. The matrix resumed after an environment check; the partial trial was restarted. See the complete evidence bundle for continuation records.` : '';
}
function renderChart(groups) {
  const key = state.metric + "_p95";
  const ciKey = state.metric + "_ci";
  const descriptions = {
    first: [
      "First correct observation",
      "Both the direct-ID read and vector-search result have shown the requested state. Acknowledgement is recorded separately. Latencies are conditional on successful confirmation.",
    ],
    confirmed: [
      "Confirmed observation",
      "At least three correct observations spanning 50ms are required on each read channel. This includes the declared confirmation window; it is not raw indexing time.",
    ],
    query: [
      "Query latency under writes",
      "Real questions search the immutable cohort while writes occur in the same index. Query latency is measured from request start to response; dispatch delays are checked separately.",
    ],
  };
  $("#chart-title").textContent = descriptions[state.metric][0];
  $("#metric-note").textContent =
    descriptions[state.metric][1] +
    " Failed gates remain visible and limit interpretation.";
  const chart = $("#chart");
  if (!groups.length) {
    chart.innerHTML =
      '<div class="empty-state">No completed evidence for this workload yet.<br>Choose a different workload or check back after the run finishes.</div>';
    chart.setAttribute(
      "aria-label",
      "No completed evidence for selected workload",
    );
    return;
  }
  const width = Math.max(chart.clientWidth, 300),
    height = 230,
    left = width < 500 ? 90 : 115,
    right = width < 500 ? 54 : 80;
  const values = groups
    .flatMap((g) => [g[key], ...(g[ciKey] || [])])
    .filter((v) => v != null && v > 0);
  const maximum = Math.pow(
    10,
    Math.ceil(Math.log10(Math.max(10, ...values) * 1.2)),
  );
  const minimum = values.length
    ? Math.min(1, Math.pow(10, Math.floor(Math.log10(Math.min(...values)))))
    : 1;
  const x = (v) =>
    left +
    ((Math.log10(Math.max(minimum, v)) - Math.log10(minimum)) /
      (Math.log10(maximum) - Math.log10(minimum))) *
      (width - left - right);
  let svg = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg"><title>${esc(descriptions[state.metric][0])}</title><desc>Median trial p95 and 95 percent bootstrap interval. Values in milliseconds. ${groups.map((g) => names[g.backend] + ": " + ms(g[key])).join(". ")}</desc>`;
  for (
    let power = Math.floor(Math.log10(minimum));
    power <= Math.ceil(Math.log10(maximum));
    power++
  ) {
    for (const multiplier of [1, 3]) {
      const value = 10 ** power * multiplier;
      if (value < minimum || value > maximum) continue;
      const xx = x(value);
      svg += `<line x1="${xx}" y1="15" x2="${xx}" y2="185" stroke="#e5e7eb" stroke-width="1"/><text x="${xx}" y="211" text-anchor="middle" fill="#6b7280" font-family="Arial, sans-serif" font-size="10">${value < 1 ? value.toFixed(1) : value.toLocaleString()}</text>`;
    }
  }
  groups.forEach((g, i) => {
    const y = 43 + i * 62;
    const value = g[key];
    const ci = g[ciKey] || [];
    const color = g.eligible ? "#2563eb" : "#a16207";
    svg += `<g class="chart-row" tabindex="0" role="button" data-engine="${esc(g.backend)}" aria-label="Inspect ${esc(names[g.backend])} trials"><text x="0" y="${y + 4}" fill="#1f2937" font-size="13" font-weight="500">${names[g.backend]}</text>`;
    if (value != null) {
      const xx = x(value);
      const lo = x(ci[0] ?? value),
        hi = x(ci[1] ?? value);
      svg += `<line x1="${left}" y1="${y}" x2="${xx}" y2="${y}" stroke="#dbe3ec" stroke-width="2"/><line x1="${lo}" y1="${y}" x2="${hi}" y2="${y}" stroke="${color}" stroke-width="2"/><line x1="${lo}" y1="${y - 5}" x2="${lo}" y2="${y + 5}" stroke="${color}"/><line x1="${hi}" y1="${y - 5}" x2="${hi}" y2="${y + 5}" stroke="${color}"/><circle cx="${xx}" cy="${y}" r="6" fill="${color}" stroke="#ffffff" stroke-width="2"/><text x="${width - 2}" y="${y + 4}" text-anchor="end" fill="${color}" font-family="Arial, sans-serif" font-size="12">${num(value)}</text>`;
    } else
      svg += `<text x="${left}" y="${y + 4}" fill="#6b7280" font-size="12">No successful observations</text>`;
    svg += "</g>";
  });
  svg += "</svg>";
  chart.innerHTML = svg;
  chart.setAttribute(
    "aria-label",
    descriptions[state.metric][0] +
      ": " +
      groups
        .map(
          (g) =>
            names[g.backend] +
            " " +
            ms(g[key]) +
            (g.eligible ? "" : "; validity limits apply"),
        )
        .join(", "),
  );
  chart.querySelectorAll("[data-engine]").forEach((g) => {
    g.addEventListener("click", () => openGroup(g.dataset.engine));
    g.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openGroup(g.dataset.engine);
      }
    });
  });
}
function renderTable(groups) {
  $("#results-table tbody").innerHTML = groups
    .map(
      (g) =>
        `<tr><td class="engine">${names[g.backend]}<small>${version(g.backend) ? "v" + esc(version(g.backend)) : "Version not recorded"} · ${g.trials}/${g.expected_trials} trials</small></td><td>${pct(g.success_rate)}<small class="sr-only"> of all submitted events</small></td><td>${ms(g.first_p95)}</td><td>${ms(g.confirmed_p95)}</td><td>${pct(g.ann_recall)}</td><td><span class="status ${g.eligible ? "" : "failed"}" title="${esc(g.failed_gates.join(", ") || "All complete trials must pass")}">${g.failed_runs ? "Setup failed" : g.eligible ? "All gates pass" : g.failed_gates.length ? "Limits apply" : "Incomplete"}</span></td><td><button class="inspect" data-inspect="${g.backend}" aria-label="Inspect ${names[g.backend]} trials">Details</button></td></tr>`,
    )
    .join("");
  document
    .querySelectorAll("[data-inspect]")
    .forEach((b) =>
      b.addEventListener("click", () => openGroup(b.dataset.inspect)),
    );
}
function renderRuns() {
  let runs = DATA.runs
    .filter((r) => r.scenario === state.scenario)
    .sort((a, b) => a.trial - b.trial || a.backend.localeCompare(b.backend));
  const visible = state.expanded ? runs : runs.slice(0, 6);
  $("#run-list").innerHTML =
    visible
      .map(
        (r) =>
          `<button data-run="${esc(r.run)}"><span>${names[r.backend]} <small> / TRIAL ${r.trial}</small></span><small>${r.status !== "complete" ? "SETUP FAILED" : r.eligible ? "GATES PASS" : "LIMITS APPLY"}</small><span aria-hidden="true">↗</span></button>`,
      )
      .join("") +
    (runs.length > 6
      ? `<button id="more-runs"><span>${state.expanded ? "Show fewer trials" : `Show all ${runs.length} trials`}</span><span></span><span aria-hidden="true">${state.expanded ? "−" : "+"}</span></button>`
      : "");
  $("#more-runs")?.addEventListener("click", () => {
    state.expanded = !state.expanded;
    renderRuns();
  });
  bindRuns($("#run-list"));
}
function bindRuns(container) {
  container
    .querySelectorAll("[data-run]")
    .forEach((b) => b.addEventListener("click", () => openRun(b.dataset.run)));
}
function openDialog(html) {
  $("#details-content").innerHTML = html;
  if (!$("#details-dialog").open) $("#details-dialog").showModal();
  $("#close-dialog").focus();
}
function openGroup(backend) {
  const group = selectedGroups().find((g) => g.backend === backend);
  if (!group) return;
  const runs = group.run_ids.map((id) => DATA.runs.find((r) => r.run === id));
  openDialog(
    `<h2>${names[backend]} <span class="detail-subtitle">/ ${esc(labels[state.scenario])}</span></h2><p class="detail-subtitle">${state.operation.toUpperCase()} · ${group.events.toLocaleString()} submitted events · ${group.trials}/${group.expected_trials} trials</p>${group.eligible ? "" : `<div class="notice">Interpretation limits: ${esc(group.failed_gates.join(", ") || "Incomplete or failed trials")}. These observations are retained, but this cell is not eligible for an unqualified comparison.</div>`}<div class="detail-grid"><section><h3>FRESHNESS AND RELIABILITY</h3><p>First observed p95: <strong>${ms(group.first_p95)}</strong></p><p>95% interval: [${num(group.first_ci[0])}, ${num(group.first_ci[1])}] ms</p><p>Confirmed within 100ms: ${pct(group.within_100ms)}</p><p>Confirmed within 1 second: ${pct(group.within_1000ms)}</p><p>Observed regressions: ${group.regressions}</p></section><section><h3>QUALITY UNDER WRITES</h3><p>ANN recall@10: ${pct(group.ann_recall)}</p><p>nDCG@10: ${num(group.ndcg)}</p><p>Exact-vector nDCG@10: ${num(group.exact_ndcg)}</p><p>Idle query p95: ${ms(group.idle_query_p95)}</p><p>Loaded query p95: ${ms(group.query_p95)}</p></section></div><h3>Inspect a trial</h3><div class="run-list">${runs.map((r) => `<button data-run="${esc(r.run)}"><span>Trial ${r.trial}</span><small>${r.status === "complete" ? (r.eligible ? "GATES PASS" : "LIMITS APPLY") : "SETUP FAILED"}</small><span>↗</span></button>`).join("")}</div>`,
  );
  bindRuns($("#details-content"));
}
function openRun(id) {
  const run = DATA.runs.find((r) => r.run === id);
  if (!run) return;
  const s = run.summary;
  let html = `<h2>${names[run.backend]} / Trial ${run.trial}</h2><p class="detail-subtitle">${esc(labels[run.scenario])}<br>${esc(id)}</p>`;
  if (!s) {
    html += `<div class="notice">Setup failed. This planned run remains in the experiment inventory.</div><pre>${esc(run.error || run.failure?.error)}</pre><a href="data/evidence/${id}-failure.json.gz" download>Download failure evidence ↓</a>`;
    openDialog(html);
    return;
  }
  html += `<div class="detail-grid"><section><h3>CONFIGURATION</h3><p>${s.metadata.base_count.toLocaleString()} immutable documents + ${s.metadata.preloaded_mutable.toLocaleString()} initial mutation targets</p><p>${s.config.duration_s}s measured · ${s.config.rate} writes/s ${s.config.arrival === "burst" ? `(×${s.config.burst_multiplier} bursts)` : ""}</p><p>${s.config.query_rate} background queries/s · top-10</p><p>${s.config.probe_workers} probe workers · ${s.config.poll_ms}ms minimum gap</p><p>${resources(run.backend)} · version ${esc(s.metadata.backend_before.version)}</p></section><section><h3>VALIDITY CHECKS</h3><ul class="gate-list">${Object.entries(
    s.gates,
  )
    .map(
      ([key, ok]) =>
        `<li><span>${esc(key.replaceAll("_", " "))}</span><span class="status ${ok ? "" : "failed"}">${ok ? "PASS" : "FAIL"}</span></li>`,
    )
    .join(
      "",
    )}</ul></section></div><div class="detail-grid"><section><h3>CLIENT OBSERVATION</h3><p>Arrival lag p95: ${ms(s.diagnostics.schedule_delay_ms.p95)}</p><p>Probe dispatch lag p95: ${ms(s.diagnostics.probe_dispatch_ms.p95)}</p><p>Probe request p95: ${ms(s.diagnostics.probe_service_ms.p95)}</p><p>Write request p95: ${ms(s.diagnostics.write_service_ms.p95)}</p></section><section><h3>QUERY QUALITY</h3><p>ANN recall@10: ${pct(s.query.ann_recall_at_10)}</p><p>nDCG@10: ${num(s.query.ndcg_at_10)}</p><p>Query p95: ${ms(s.query.latency_ms.p95)}</p><p>${s.query.success}/${s.query.count} background queries succeeded</p></section></div><h3>Actual event observations</h3><p class="detail-subtitle">One successful example per operation. Times are relative to submission; examples do not represent the distribution.</p>`;
  for (const event of run.examples || []) {
    if (!event) continue;
    html += `<div class="timeline"><b>${event.operation.toUpperCase()} / ${esc(event.doc_id)}</b><div><span>ACK<br>${ms(event.ack_ms)}</span><span>FIRST CONTROL<br>${ms(event.control.first_ms)}</span><span>FIRST SEARCH<br>${ms(event.search.first_ms)}</span><span>CONFIRMED<br>${ms(event.confirmed_ms)}</span></div></div>`;
  }
  html += `<div class="detail-links">${["summary.json", "events.jsonl", "probes.jsonl", "queries.jsonl", "reference.json"].map((name) => `<a href="data/evidence/${id}-${name}.gz" download>${name} ↓</a>`).join("")}</div><details><summary>Effective backend configuration</summary><pre>${esc(JSON.stringify(s.metadata.backend_before, null, 2))}</pre></details>`;
  openDialog(html);
}
function renderCalibration() {
  const rows = DATA.calibration.map((c) => {
    const first = Object.values(c.operations)
      .map((o) => o.first_observed_ms.p50)
      .filter((v) => v != null);
    const observed = first.length
      ? first.reduce((a, b) => a + b, 0) / first.length
      : null;
    return `<tr><td>${c.injected_visibility_ms} ms</td><td>${c.injected_ack_ms} ms</td><td>${ms(observed)}</td><td>${c.statuses.success}/${c.total_operations}</td></tr>`;
  });
  $("#calibration-table").innerHTML =
    '<table><caption class="sr-only">Known-delay calibration results</caption><thead><tr><th>VISIBILITY DELAY</th><th>ACK DELAY</th><th>MEAN OF OPERATION p50s</th><th>CONFIRMED</th></tr></thead><tbody>' +
    rows.join("") +
    "</tbody></table>";
}
function renderDatasets() {
  const descriptions = {
    nq: "Questions asked by real search users, paired with Wikipedia passages and relevance judgments. A deterministic subset preserves all relevant documents for the selected 100 test questions before reservoir sampling the remaining corpus.",
    scifact:
      "Scientific claims paired with research abstracts and evidence judgments. A compact retrieval task used to validate version semantics and quality on a second domain.",
  };
  $("#dataset-list").innerHTML = Object.entries(DATA.experiment.datasets)
    .map(
      ([key, d], i) =>
        `<article class="dataset"><div><h2>${key === "nq" ? "Natural Questions" : "SciFact"}</h2><p>${descriptions[key]}</p><div class="meta-row"><div><strong>${d.records.toLocaleString()}</strong><span>CACHED DOCUMENTS</span></div><div><strong>${d.queries}</strong><span>REAL QUESTIONS</span></div><div><strong>384</strong><span>VECTOR DIMENSIONS</span></div></div><p><strong>License:</strong> ${esc(d.license)}</p><p>${esc(d.attribution)}</p><p>${esc(d.transformation)}</p><a class="small-link" href="data/${key}-manifest.json" download>Manifest + hashes ↓</a><a class="small-link" href="data/${key}-LICENSE.md" download>Upstream license ↓</a><a class="small-link" href="${esc(d.source)}">Source archive ↗</a></div></article>`,
    )
    .join("");
}
$("#scenario").addEventListener("change", (e) => {
  state.scenario = e.target.value;
  state.expanded = false;
  changeHash();
});
$("#metric").addEventListener("change", (e) => {
  state.metric = e.target.value;
  changeHash();
});
document.querySelectorAll("[data-op]").forEach((b) =>
  b.addEventListener("click", () => {
    state.operation = b.dataset.op;
    changeHash();
  }),
);
$("#close-dialog").addEventListener("click", () =>
  $("#details-dialog").close(),
);
$("#details-dialog").addEventListener("click", (e) => {
  if (e.target === $("#details-dialog")) {
    const r = e.target.getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      e.target.close();
  }
});
$("#share").addEventListener("click", async () => {
  try {
    const url = new URL(location.href);
    url.search = '';
    url.hash = 'results?' + new URLSearchParams({scenario: state.scenario, operation: state.operation, metric: state.metric});
    history.replaceState(null, '', url);
    await navigator.clipboard.writeText(url.href);
    toast("Comparison link copied");
  } catch {
    toast("Copy the current URL to share this comparison");
  }
});
document.querySelectorAll(".copy-code").forEach((b) =>
  b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(
        document.getElementById(b.dataset.target).textContent,
      );
      toast("Commands copied");
    } catch {
      toast("Select the commands to copy them");
    }
  }),
);
window.addEventListener("hashchange", () => {
  const before = state.page;
  hashState();
  if (before !== state.page) window.scrollTo({ top: 0, behavior: "instant" });
});
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (DATA) renderChart(selectedGroups());
  }, 100);
});
hashState();
fetch("data/results.json")
  .then((r) => {
    if (!r.ok) throw Error("Evidence is not available yet");
    return r.json();
  })
  .then((data) => {
    DATA = data;
    render();
  })
  .catch((error) => {
    $("#run-status").textContent = "Evidence unavailable";
    $("#chart").innerHTML =
      `<div class="empty-state">${esc(error.message)}.<br>Please reload after the experiment export finishes.</div>`;
  });
