from __future__ import annotations

import csv
import json
from pathlib import Path

from .reporting import metric_stats


def _safe_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _find_latest_run_dir(artifacts_dir: Path) -> Path:
    if not artifacts_dir.exists():
        raise FileNotFoundError(f"Artifacts directory not found: {artifacts_dir}")
    candidates: list[Path] = []
    for child in artifacts_dir.iterdir():
        if not child.is_dir():
            continue
        if (child / "summary.json").exists() and (child / "metrics.csv").exists():
            candidates.append(child)
    if not candidates:
        raise FileNotFoundError(
            f"No run directories with summary.json and metrics.csv in {artifacts_dir}"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _histogram(values: list[float], bins: int = 20) -> tuple[list[int], float, float]:
    if not values:
        return [0] * bins, 0.0, 1.0
    min_v = min(values)
    max_v = max(values)
    if min_v == max_v:
        max_v = min_v + 1.0
    counts = [0 for _ in range(bins)]
    for value in values:
        normalized = (value - min_v) / (max_v - min_v)
        idx = min(int(normalized * bins), bins - 1)
        counts[idx] += 1
    return counts, min_v, max_v


def _cdf_points(values: list[float]) -> list[tuple[float, float]]:
    if not values:
        return []
    ordered = sorted(values)
    total = len(ordered)
    return [(value, (i + 1) / total) for i, value in enumerate(ordered)]


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f} ms"


def _svg_histogram(values: list[float], width: int = 860, height: int = 300) -> str:
    bins = 20
    counts, min_v, max_v = _histogram(values, bins=bins)
    margin_l = 56
    margin_r = 20
    margin_t = 24
    margin_b = 42
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    max_count = max(counts) if counts else 1
    bar_w = plot_w / bins

    rects: list[str] = []
    for i, count in enumerate(counts):
        h = 0 if max_count == 0 else (count / max_count) * plot_h
        x = margin_l + (i * bar_w) + 1
        y = margin_t + (plot_h - h)
        rects.append(
            f"<rect x='{x:.2f}' y='{y:.2f}' width='{max(bar_w - 2, 1):.2f}' "
            f"height='{h:.2f}' fill='#127a6c' opacity='0.88' />"
        )

    mid = (min_v + max_v) / 2
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Freshness histogram'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f8f6ee'/>"
        f"<line x1='{margin_l}' y1='{margin_t + plot_h}' x2='{margin_l + plot_w}' y2='{margin_t + plot_h}' stroke='#20303a' stroke-width='1'/>"
        f"<line x1='{margin_l}' y1='{margin_t}' x2='{margin_l}' y2='{margin_t + plot_h}' stroke='#20303a' stroke-width='1'/>"
        f"{''.join(rects)}"
        f"<text x='{margin_l}' y='{height - 12}' font-size='12' fill='#20303a'>{min_v:.0f} ms</text>"
        f"<text x='{margin_l + plot_w / 2 - 30}' y='{height - 12}' font-size='12' fill='#20303a'>{mid:.0f} ms</text>"
        f"<text x='{margin_l + plot_w - 56}' y='{height - 12}' font-size='12' fill='#20303a'>{max_v:.0f} ms</text>"
        f"<text x='10' y='{margin_t + 12}' font-size='12' fill='#20303a'>{max_count}</text>"
        "</svg>"
    )


def _svg_cdf(values: list[float], width: int = 860, height: int = 300) -> str:
    points = _cdf_points(values)
    if not points:
        return "<svg viewBox='0 0 860 300'></svg>"

    margin_l = 56
    margin_r = 20
    margin_t = 24
    margin_b = 42
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    min_x = points[0][0]
    max_x = points[-1][0]
    if min_x == max_x:
        max_x = min_x + 1.0

    poly_pts: list[str] = []
    for x, y in points:
        px = margin_l + ((x - min_x) / (max_x - min_x)) * plot_w
        py = margin_t + (1.0 - y) * plot_h
        poly_pts.append(f"{px:.2f},{py:.2f}")

    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Freshness CDF'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f8f6ee'/>"
        f"<line x1='{margin_l}' y1='{margin_t + plot_h}' x2='{margin_l + plot_w}' y2='{margin_t + plot_h}' stroke='#20303a' stroke-width='1'/>"
        f"<line x1='{margin_l}' y1='{margin_t}' x2='{margin_l}' y2='{margin_t + plot_h}' stroke='#20303a' stroke-width='1'/>"
        f"<polyline fill='none' stroke='#b23a48' stroke-width='3' points='{' '.join(poly_pts)}' />"
        f"<text x='{margin_l}' y='{height - 12}' font-size='12' fill='#20303a'>{min_x:.0f} ms</text>"
        f"<text x='{margin_l + plot_w - 56}' y='{height - 12}' font-size='12' fill='#20303a'>{max_x:.0f} ms</text>"
        f"<text x='10' y='{margin_t + 12}' font-size='12' fill='#20303a'>100%</text>"
        f"<text x='14' y='{margin_t + plot_h + 4}' font-size='12' fill='#20303a'>0%</text>"
        "</svg>"
    )


def _svg_stage_bars(
    stages: list[tuple[str, float | None, float | None]],
    width: int = 860,
    height: int = 320,
) -> str:
    margin_l = 190
    margin_r = 20
    margin_t = 24
    margin_b = 24
    plot_w = width - margin_l - margin_r
    row_h = 82
    bar_h = 18
    max_value = max(
        [
            value
            for _, p50, p95 in stages
            for value in (p50, p95)
            if value is not None
        ],
        default=1.0,
    )
    if max_value <= 0:
        max_value = 1.0

    rows: list[str] = []
    for idx, (label, p50, p95) in enumerate(stages):
        top = margin_t + (idx * row_h)
        y1 = top + 18
        y2 = y1 + bar_h + 8
        p50_val = p50 or 0.0
        p95_val = p95 or 0.0
        p50_w = (p50_val / max_value) * plot_w
        p95_w = (p95_val / max_value) * plot_w
        rows.append(
            f"<text x='16' y='{top + 26}' font-size='13' fill='#20303a'>{label}</text>"
            f"<rect x='{margin_l}' y='{y1}' width='{p50_w:.2f}' height='{bar_h}' fill='#127a6c' rx='4'/>"
            f"<rect x='{margin_l}' y='{y2}' width='{p95_w:.2f}' height='{bar_h}' fill='#b23a48' rx='4'/>"
            f"<text x='{margin_l + p50_w + 8:.2f}' y='{y1 + 14}' font-size='12' fill='#20303a'>p50 {_fmt_ms(p50)}</text>"
            f"<text x='{margin_l + p95_w + 8:.2f}' y='{y2 + 14}' font-size='12' fill='#20303a'>p95 {_fmt_ms(p95)}</text>"
        )
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Stage latency breakdown'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f8f6ee'/>"
        f"<line x1='{margin_l}' y1='{height - margin_b}' x2='{margin_l + plot_w}' y2='{height - margin_b}' stroke='#20303a' stroke-width='1'/>"
        f"<text x='{margin_l}' y='{height - 6}' font-size='12' fill='#20303a'>0 ms</text>"
        f"<text x='{margin_l + plot_w - 70}' y='{height - 6}' font-size='12' fill='#20303a'>{max_value:.0f} ms</text>"
        f"{''.join(rows)}"
        "</svg>"
    )


def _load_metrics(metrics_path: Path) -> tuple[list[float], list[float], list[float], list[float]]:
    freshness: list[float] = []
    embedding: list[float] = []
    index_ack: list[float] = []
    search_gap: list[float] = []

    with metrics_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fr = _safe_float(row.get("freshness_ms"))
            em = _safe_float(row.get("embedding_ms"))
            ia = _safe_float(row.get("index_ack_ms"))
            if fr is not None:
                freshness.append(fr)
            if em is not None:
                embedding.append(em)
            if ia is not None:
                index_ack.append(ia)
            if fr is not None and em is not None and ia is not None:
                gap = fr - em - ia
                search_gap.append(gap if gap > 0 else 0.0)
    return freshness, embedding, index_ack, search_gap


def generate_html_report(run_dir: Path, out_file: Path | None = None) -> Path:
    summary_path = run_dir / "summary.json"
    metrics_path = run_dir / "metrics.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary file: {summary_path}")
    if not metrics_path.exists():
        raise FileNotFoundError(f"Missing metrics file: {metrics_path}")

    with summary_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)

    freshness_vals, _, _, search_gap_vals = _load_metrics(metrics_path)
    search_gap_stats = metric_stats(search_gap_vals)

    run_id = summary["run_id"]
    success = summary["docs_success"]
    total = summary["docs_total"]
    rate = summary["success_rate"] * 100.0
    fresh = summary["freshness_ms"]
    embed = summary["embedding_ms"]
    index_ack = summary["index_ack_ms"]

    histogram_svg = _svg_histogram(freshness_vals)
    cdf_svg = _svg_cdf(freshness_vals)
    stage_svg = _svg_stage_bars(
        [
            ("Embedding", embed["p50"], embed["p95"]),
            ("Index Ack", index_ack["p50"], index_ack["p95"]),
            ("Search Visibility Gap", search_gap_stats["p50"], search_gap_stats["p95"]),
        ]
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Freshness Report - {run_id}</title>
  <style>
    :root {{
      --paper: #f8f6ee;
      --ink: #17242d;
      --mint: #127a6c;
      --brick: #b23a48;
      --card: #fffdf7;
      --line: #d8d5c7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 10%, #f4d6c2 0%, transparent 38%),
        radial-gradient(circle at 92% 0%, #d4ebe7 0%, transparent 30%),
        var(--paper);
      padding: 28px;
    }}
    .wrap {{ max-width: 1080px; margin: 0 auto; }}
    h1 {{ margin: 0 0 6px 0; font-size: 36px; line-height: 1.05; letter-spacing: -0.02em; }}
    .sub {{ margin: 0 0 18px 0; font-size: 14px; color: #35505f; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--card);
      padding: 12px 14px;
      box-shadow: 0 4px 18px rgba(20, 35, 50, 0.06);
    }}
    .k {{ font-size: 12px; color: #496271; text-transform: uppercase; letter-spacing: 0.06em; }}
    .v {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--card);
      padding: 12px;
      margin-bottom: 14px;
      box-shadow: 0 4px 18px rgba(20, 35, 50, 0.06);
    }}
    .panel h2 {{ margin: 0 0 8px 0; font-size: 18px; }}
    .formula {{
      display: inline-block;
      margin-top: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      background: #e8f5f2;
      border: 1px solid #cae4de;
      color: #1a5d55;
      font-size: 12px;
    }}
    svg {{ width: 100%; height: auto; border-radius: 8px; }}
    @media (max-width: 920px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
      h1 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Freshness Latency Report</h1>
    <p class="sub">Run <strong>{run_id}</strong> · {success}/{total} successful · success rate {rate:.1f}%</p>
    <div class="grid">
      <div class="card"><div class="k">p50 freshness</div><div class="v">{_fmt_ms(fresh["p50"])}</div></div>
      <div class="card"><div class="k">p95 freshness</div><div class="v">{_fmt_ms(fresh["p95"])}</div></div>
      <div class="card"><div class="k">p99 freshness</div><div class="v">{_fmt_ms(fresh["p99"])}</div></div>
      <div class="card"><div class="k">max freshness</div><div class="v">{_fmt_ms(fresh["max"])}</div></div>
      <div class="card"><div class="k">documents</div><div class="v">{success}/{total}</div></div>
    </div>

    <div class="panel">
      <h2>Freshness Histogram</h2>
      {histogram_svg}
    </div>

    <div class="panel">
      <h2>Freshness CDF</h2>
      {cdf_svg}
      <span class="formula">Freshness Latency = T(searchable) - T(ingested)</span>
    </div>

    <div class="panel">
      <h2>Stage Breakdown (p50 and p95)</h2>
      {stage_svg}
    </div>
  </div>
</body>
</html>
"""
    out_path = out_file or (run_dir / "report.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def generate_report_from_args(args: object) -> Path:
    run_dir_value = getattr(args, "run_dir", None)
    out_file_value = getattr(args, "out_file", None)
    if run_dir_value:
        run_dir = Path(run_dir_value)
    else:
        artifacts_dir = Path(getattr(args, "artifacts_dir", "artifacts"))
        run_dir = _find_latest_run_dir(artifacts_dir)
    out_file = Path(out_file_value) if out_file_value else None
    return generate_html_report(run_dir=run_dir, out_file=out_file)
