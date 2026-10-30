import fs from "node:fs";
import path from "node:path";
export const data = JSON.parse(
  fs.readFileSync(
    process.env.FRESHNESS_RESULTS_FILE ||
      path.resolve("../results/mixed-v2/results.json"),
    "utf8",
  ),
);
export const names = {
  qdrant: "Qdrant",
  weaviate: "Weaviate",
  pgvector: "pgvector",
};
export const workloads = {
  "nq-100k": {
    label: "100,000 documents · steady traffic",
    short: "Natural Questions · 100k",
    description:
      "Wikipedia passages and real questions. Ten changes and ten background queries per second.",
  },
  "nq-100k-burst": {
    label: "100,000 documents · burst traffic",
    short: "Natural Questions · 100k · burst",
    description:
      "The same corpus, with 40 changes per second during one-second bursts every ten seconds.",
  },
  "nq-10k": {
    label: "10,000 documents · steady traffic",
    short: "Natural Questions · 10k",
    description:
      "A smaller Wikipedia collection. Ten changes and ten background queries per second.",
  },
  "scifact-small": {
    label: "4,000 documents · steady traffic",
    short: "SciFact · 4k",
    description:
      "Research abstracts and scientific claims. A second subject area at a smaller scale.",
  },
};
export const release =
  "https://github.com/aadithya2112/freshness-benchmark/releases";
export const repo = "https://github.com/aadithya2112/freshness-benchmark";
export const format = (value) =>
  value == null
    ? "Unavailable"
    : Number(value).toLocaleString("en-US", {
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      });
export const percent = (value) =>
  value == null ? "Unavailable" : (value * 100).toFixed(1) + "%";
export const version = (backend) =>
  data.runs.find((r) => r.backend === backend && r.summary)?.summary.metadata
    .backend_before.version || "unrecorded";
export const mutations = data.groups.reduce((n, g) => n + g.events, 0);
export const gates = {
  arrival_dispatch: "Changes were submitted on schedule",
  probe_dispatch: "Observation reads started on schedule",
  query_dispatch: "Background queries started on schedule",
  ann_recall: "Search recall met the 95% target",
  preconditions: "Every mutation had a valid starting state",
  client_capacity: "The client dropped no mutations",
  cohort_integrity: "Quality queries stayed in the intended corpus",
  ann_index_used: "The configured search index was verified",
};
