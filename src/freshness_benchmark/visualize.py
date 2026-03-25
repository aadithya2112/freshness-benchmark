from __future__ import annotations

import csv
import html
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


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}/s"


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
            f"height='{h:.2f}' fill='#0f766e' opacity='0.9' />"
        )

    mid = (min_v + max_v) / 2
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Freshness histogram'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f7f7f2'/>"
        f"<line x1='{margin_l}' y1='{margin_t + plot_h}' x2='{margin_l + plot_w}' y2='{margin_t + plot_h}' stroke='#1f2937' stroke-width='1'/>"
        f"<line x1='{margin_l}' y1='{margin_t}' x2='{margin_l}' y2='{margin_t + plot_h}' stroke='#1f2937' stroke-width='1'/>"
        f"{''.join(rects)}"
        f"<text x='{margin_l}' y='{height - 12}' font-size='12' fill='#1f2937'>{min_v:.0f} ms</text>"
        f"<text x='{margin_l + plot_w / 2 - 30}' y='{height - 12}' font-size='12' fill='#1f2937'>{mid:.0f} ms</text>"
        f"<text x='{margin_l + plot_w - 56}' y='{height - 12}' font-size='12' fill='#1f2937'>{max_v:.0f} ms</text>"
        f"<text x='10' y='{margin_t + 12}' font-size='12' fill='#1f2937'>{max_count}</text>"
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
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f7f7f2'/>"
        f"<line x1='{margin_l}' y1='{margin_t + plot_h}' x2='{margin_l + plot_w}' y2='{margin_t + plot_h}' stroke='#1f2937' stroke-width='1'/>"
        f"<line x1='{margin_l}' y1='{margin_t}' x2='{margin_l}' y2='{margin_t + plot_h}' stroke='#1f2937' stroke-width='1'/>"
        f"<polyline fill='none' stroke='#be123c' stroke-width='3' points='{' '.join(poly_pts)}' />"
        f"<text x='{margin_l}' y='{height - 12}' font-size='12' fill='#1f2937'>{min_x:.0f} ms</text>"
        f"<text x='{margin_l + plot_w - 56}' y='{height - 12}' font-size='12' fill='#1f2937'>{max_x:.0f} ms</text>"
        f"<text x='10' y='{margin_t + 12}' font-size='12' fill='#1f2937'>100%</text>"
        f"<text x='14' y='{margin_t + plot_h + 4}' font-size='12' fill='#1f2937'>0%</text>"
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
            f"<text x='16' y='{top + 26}' font-size='13' fill='#1f2937'>{html.escape(label)}</text>"
            f"<rect x='{margin_l}' y='{y1}' width='{p50_w:.2f}' height='{bar_h}' fill='#0f766e' rx='4'/>"
            f"<rect x='{margin_l}' y='{y2}' width='{p95_w:.2f}' height='{bar_h}' fill='#be123c' rx='4'/>"
            f"<text x='{margin_l + p50_w + 8:.2f}' y='{y1 + 14}' font-size='12' fill='#1f2937'>p50 {_fmt_ms(p50)}</text>"
            f"<text x='{margin_l + p95_w + 8:.2f}' y='{y2 + 14}' font-size='12' fill='#1f2937'>p95 {_fmt_ms(p95)}</text>"
        )
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Stage latency breakdown'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f7f7f2'/>"
        f"<line x1='{margin_l}' y1='{height - margin_b}' x2='{margin_l + plot_w}' y2='{height - margin_b}' stroke='#1f2937' stroke-width='1'/>"
        f"<text x='{margin_l}' y='{height - 6}' font-size='12' fill='#1f2937'>0 ms</text>"
        f"<text x='{margin_l + plot_w - 70}' y='{height - 6}' font-size='12' fill='#1f2937'>{max_value:.0f} ms</text>"
        f"{''.join(rows)}"
        "</svg>"
    )


def _svg_compare_lines(rows: list[dict[str, object]], width: int = 860, height: int = 320) -> str:
    if not rows:
        return "<svg viewBox='0 0 860 320'></svg>"
    margin_l = 56
    margin_r = 20
    margin_t = 24
    margin_b = 42
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    rates = sorted({float(row["rate"]) for row in rows})
    freshness = [
        float(row["freshness_p95_ms"])
        for row in rows
        if row.get("freshness_p95_ms") is not None
    ]
    if not freshness:
        freshness = [1.0]
    min_x = min(rates)
    max_x = max(rates)
    if min_x == max_x:
        max_x = min_x + 1.0
    max_y = max(freshness)
    if max_y <= 0:
        max_y = 1.0

    palette = ["#0f766e", "#be123c", "#1d4ed8", "#a16207", "#7c3aed"]
    series: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        key = f"{row['backend']} / {row['embedding_mode']}"
        series.setdefault(key, []).append(row)

    polylines: list[str] = []
    legends: list[str] = []
    for idx, (label, points) in enumerate(sorted(series.items())):
        color = palette[idx % len(palette)]
        ordered = sorted(points, key=lambda item: float(item["rate"]))
        coords = []
        for point in ordered:
            x = float(point["rate"])
            y = float(point["freshness_p95_ms"] or 0.0)
            px = margin_l + ((x - min_x) / (max_x - min_x)) * plot_w
            py = margin_t + plot_h - ((y / max_y) * plot_h)
            coords.append(f"{px:.2f},{py:.2f}")
        polylines.append(
            f"<polyline fill='none' stroke='{color}' stroke-width='3' points='{' '.join(coords)}' />"
        )
        legends.append(
            f"<div class='legend-item'><span class='swatch' style='background:{color}'></span>{html.escape(label)}</div>"
        )

    svg = (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='p95 freshness by rate'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f7f7f2'/>"
        f"<line x1='{margin_l}' y1='{margin_t + plot_h}' x2='{margin_l + plot_w}' y2='{margin_t + plot_h}' stroke='#1f2937' stroke-width='1'/>"
        f"<line x1='{margin_l}' y1='{margin_t}' x2='{margin_l}' y2='{margin_t + plot_h}' stroke='#1f2937' stroke-width='1'/>"
        f"{''.join(polylines)}"
        f"<text x='{margin_l}' y='{height - 12}' font-size='12' fill='#1f2937'>{min_x:.1f}/s</text>"
        f"<text x='{margin_l + plot_w - 56}' y='{height - 12}' font-size='12' fill='#1f2937'>{max_x:.1f}/s</text>"
        f"<text x='8' y='{margin_t + 12}' font-size='12' fill='#1f2937'>{max_y:.0f} ms</text>"
        "</svg>"
    )
    return svg + "<div class='legend'>" + "".join(legends) + "</div>"


def _load_metrics(
    metrics_path: Path,
) -> tuple[list[float], list[float], list[float], list[float]]:
    freshness: list[float] = []
    embedding: list[float] = []
    write_ack: list[float] = []
    visibility: list[float] = []

    with metrics_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fr = _safe_float(row.get("freshness_ms"))
            em = _safe_float(row.get("embedding_ms"))
            wa = _safe_float(row.get("write_ack_ms"))
            vis = _safe_float(row.get("visibility_ms"))
            if fr is not None:
                freshness.append(fr)
            if em is not None:
                embedding.append(em)
            if wa is not None:
                write_ack.append(wa)
            if vis is not None:
                visibility.append(vis)
    return freshness, embedding, write_ack, visibility


def generate_html_report(run_dir: Path, out_file: Path | None = None) -> Path:
    summary_path = run_dir / "summary.json"
    metrics_path = run_dir / "metrics.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary file: {summary_path}")
    if not metrics_path.exists():
        raise FileNotFoundError(f"Missing metrics file: {metrics_path}")

    with summary_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)

    freshness_vals, embedding_vals, write_vals, visibility_vals = _load_metrics(metrics_path)
    visibility_stats = metric_stats(visibility_vals)

    histogram_svg = _svg_histogram(freshness_vals)
    cdf_svg = _svg_cdf(freshness_vals)
    stage_svg = _svg_stage_bars(
        [
            ("Embedding", summary["embedding_ms"]["p50"], summary["embedding_ms"]["p95"]),
            ("Write Ack", summary["write_ack_ms"]["p50"], summary["write_ack_ms"]["p95"]),
            ("Visibility", visibility_stats["p50"], visibility_stats["p95"]),
        ]
    )

    backend_info = json.dumps(summary.get("backend_info", {}), indent=2)
    environment = json.dumps(summary.get("environment", {}), indent=2)
    dataset_info = json.dumps(summary.get("dataset", {}), indent=2)
    source_label = (
        f"dataset {html.escape(str(summary['dataset'].get('format')))}"
        if summary.get("dataset")
        else html.escape(summary["workload"])
    )
    html_content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Freshness Report - {html.escape(summary['run_id'])}</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #14213d;
      --muted: #536271;
      --line: #ddd6c8;
      --accent: #0f766e;
      --accent-2: #be123c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(15,118,110,0.10), transparent 32%),
        radial-gradient(circle at 100% 0%, rgba(190,18,60,0.10), transparent 28%),
        var(--bg);
      padding: 28px;
    }}
    .wrap {{ max-width: 1120px; margin: 0 auto; }}
    h1 {{ margin: 0 0 6px 0; font-size: 36px; line-height: 1.02; letter-spacing: -0.03em; }}
    .sub {{ margin: 0 0 20px 0; color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card, .panel {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel);
      box-shadow: 0 8px 28px rgba(20, 33, 61, 0.05);
    }}
    .card {{ padding: 14px; }}
    .panel {{ padding: 14px; margin-bottom: 14px; }}
    .k {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
    .v {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(280px, 1fr));
      gap: 14px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "SFMono-Regular", "Menlo", monospace;
      font-size: 12px;
      color: #233143;
    }}
    svg {{ width: 100%; height: auto; border-radius: 10px; }}
    @media (max-width: 980px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
      .meta {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Freshness Benchmark V2</h1>
    <p class="sub">Run <strong>{html.escape(summary['run_id'])}</strong> on <strong>{html.escape(summary['backend'])}</strong> · mode <strong>{html.escape(summary['embedding_mode'])}</strong> · source <strong>{source_label}</strong></p>
    <div class="grid">
      <div class="card"><div class="k">p50 freshness</div><div class="v">{_fmt_ms(summary['freshness_ms']['p50'])}</div></div>
      <div class="card"><div class="k">p95 freshness</div><div class="v">{_fmt_ms(summary['freshness_ms']['p95'])}</div></div>
      <div class="card"><div class="k">p50 embedding</div><div class="v">{_fmt_ms(summary['embedding_ms']['p50'])}</div></div>
      <div class="card"><div class="k">p50 write ack</div><div class="v">{_fmt_ms(summary['write_ack_ms']['p50'])}</div></div>
      <div class="card"><div class="k">p50 visibility</div><div class="v">{_fmt_ms(summary['visibility_ms']['p50'])}</div></div>
      <div class="card"><div class="k">success rate</div><div class="v">{summary['success_rate'] * 100.0:.1f}%</div></div>
    </div>
    <div class="grid">
      <div class="card"><div class="k">requested rate</div><div class="v">{_fmt_rate(summary['requested_rate'])}</div></div>
      <div class="card"><div class="k">submit rate</div><div class="v">{_fmt_rate(summary['actual_submission_rate'])}</div></div>
      <div class="card"><div class="k">completion rate</div><div class="v">{_fmt_rate(summary['actual_completion_rate'])}</div></div>
      <div class="card"><div class="k">documents</div><div class="v">{summary['docs_success']}/{summary['docs_total']}</div></div>
      <div class="card"><div class="k">wall clock</div><div class="v">{summary['wall_clock_s']:.1f}s</div></div>
      <div class="card"><div class="k">timeouts/errors</div><div class="v">{summary['docs_timeout']}/{summary['docs_error']}</div></div>
    </div>
    <div class="panel">
      <h2>Freshness Histogram</h2>
      {histogram_svg}
    </div>
    <div class="panel">
      <h2>Freshness CDF</h2>
      {cdf_svg}
    </div>
    <div class="panel">
      <h2>Stage Breakdown</h2>
      {stage_svg}
    </div>
    <div class="meta">
      <div class="panel">
        <h2>Dataset</h2>
        <pre>{html.escape(dataset_info)}</pre>
      </div>
      <div class="panel">
        <h2>Backend Info</h2>
        <pre>{html.escape(backend_info)}</pre>
      </div>
      <div class="panel">
        <h2>Environment</h2>
        <pre>{html.escape(environment)}</pre>
      </div>
    </div>
  </div>
</body>
</html>
"""
    out_path = out_file or (run_dir / "report.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content, encoding="utf-8")
    return out_path


def generate_comparison_html_report(
    comparison_json: Path,
    out_file: Path | None = None,
) -> Path:
    with comparison_json.open("r", encoding="utf-8") as f:
        comparison = json.load(f)
    rows = comparison.get("rows", [])

    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['backend']))}</td>"
            f"<td>{html.escape(str(row['embedding_mode']))}</td>"
            f"<td>{float(row['rate']):.2f}</td>"
            f"<td>{_fmt_ms(row.get('freshness_p50_ms'))}</td>"
            f"<td>{_fmt_ms(row.get('freshness_p95_ms'))}</td>"
            f"<td>{row['success_rate'] * 100.0:.1f}%</td>"
            f"<td>{_fmt_rate(row.get('actual_completion_rate'))}</td>"
            "</tr>"
        )

    chart = _svg_compare_lines(rows)
    html_content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Freshness Comparison - {html.escape(str(comparison['compare_id']))}</title>
  <style>
    :root {{
      --bg: #f2eee6;
      --panel: #fffdf8;
      --ink: #1f2937;
      --line: #ddd6c8;
      --muted: #55606d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
      background:
        linear-gradient(180deg, rgba(15,118,110,0.08), transparent 22%),
        var(--bg);
      color: var(--ink);
      padding: 28px;
    }}
    .wrap {{ max-width: 1120px; margin: 0 auto; }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel);
      padding: 14px;
      margin-bottom: 14px;
      box-shadow: 0 8px 28px rgba(20, 33, 61, 0.05);
    }}
    h1 {{ margin: 0 0 6px 0; font-size: 36px; line-height: 1.02; }}
    .sub {{ margin: 0 0 20px 0; color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 14px;
    }}
    th {{ color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-size: 12px; }}
    svg {{ width: 100%; height: auto; border-radius: 10px; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }}
    .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); }}
    .swatch {{ width: 12px; height: 12px; border-radius: 999px; display: inline-block; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Freshness Comparison</h1>
    <p class="sub">Comparison <strong>{html.escape(str(comparison['compare_id']))}</strong> across {len(rows)} runs</p>
    <div class="panel">
      <h2>p95 Freshness By Ingest Rate</h2>
      {chart}
    </div>
    <div class="panel">
      <h2>Comparison Table</h2>
      <table>
        <thead>
          <tr>
            <th>Backend</th>
            <th>Embedding Mode</th>
            <th>Rate</th>
            <th>p50 Freshness</th>
            <th>p95 Freshness</th>
            <th>Success Rate</th>
            <th>Completion Rate</th>
          </tr>
        </thead>
        <tbody>
          {''.join(table_rows)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""
    target = out_file or (comparison_json.parent / "comparison.html")
    target.write_text(html_content, encoding="utf-8")
    return target


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
