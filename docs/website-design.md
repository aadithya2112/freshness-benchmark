# Astro website and reading flow

The website uses Astro static pages, a system sans-serif font, white surfaces,
blue links, and readable 16–20px body text. The layout introduces the question,
shows a scoped result preview, explains the three measurement steps, and then
invites readers into the full comparison.

The results page places a compact set of controls above three database rows.
An interactive bar chart shows latency with 95% trial-bootstrap whiskers and a zero-based linear axis. It supports pointer, touch, and keyboard inspection and updates with every filter. Each row gives one primary latency estimate, its trial-level interval,
confirmation rate, and search recall. Technical metrics and individual trial
links use native expandable sections. A reading guide explains milliseconds,
p95, recall, and validity checks alongside the comparison.

Methodology and reproduction pages use a restrained contents column and a
comfortable article width. Mobile stacks the layout without a wide comparison
table. Trial records have separate static pages with evidence links. System
fonts, visible keyboard focus, native controls, and reduced-motion support keep
the interface accessible and lightweight.

The frontend and Sites skills guide implementation. The data-oriented
[ANN-Benchmarks](https://ann-benchmarks.com/) and
[ClickBench](https://benchmark.clickhouse.com/) remain useful reference patterns;
this iteration adds a gentler explanatory path for first-time readers.

See [web/README.md](../web/README.md) for the build commands. All scores come
from the audited experiment, and immutable version 0.5.0 downloads retain
their release hashes when the website is rebuilt.
