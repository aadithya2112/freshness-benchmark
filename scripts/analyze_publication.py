#!/usr/bin/env python3
"""Aggregate independent trials and export an auditable report and scientific figure."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import random
import statistics

from freshness_benchmark.reporting import percentile


def interval(values):
    if len(values) < 2:
        return [None, None]
    rng = random.Random(20261028)
    samples = [statistics.median(rng.choices(values, k=len(values))) for _ in range(10000)]
    return [percentile(samples, 2.5), percentile(samples, 97.5)]


def analyze(root):
    experiment = json.loads((root/'experiment.json').read_text())
    progress = [json.loads(line) for line in (root/'progress.jsonl').read_text().splitlines()]
    groups, records = {}, {}
    for entry in progress:
        run = root/'runs'/Path(entry['run_dir']).name
        summary = json.loads((run/'summary.json').read_text())
        traces = [json.loads(line) for line in (run/'trace.jsonl').read_text().splitlines()]
        key = (entry['backend'], entry['rate'])
        groups.setdefault(key, []).append((summary, traces))
        records.setdefault(key, []).extend(traces)
    rows = []
    for (backend, rate), trials in sorted(groups.items()):
        p95s = [s['freshness_ms']['p95'] for s,t in trials if s['freshness_ms']['p95'] is not None]
        all_records = records[(backend, rate)]
        n = len(all_records)
        row = {'backend': backend, 'rate': rate, 'trials': len(trials), 'documents': n,
               'success_rate': sum(r['status']=='success' for r in all_records)/n,
               'median_trial_p50_ms': statistics.median([s['freshness_ms']['p50'] for s,t in trials if s['freshness_ms']['p50'] is not None]) if p95s else None,
               'median_trial_p95_ms': statistics.median(p95s) if p95s else None,
               'p95_trial_bootstrap_95_low_ms': interval(p95s)[0],
               'p95_trial_bootstrap_95_high_ms': interval(p95s)[1],
               'max_trial_schedule_p95_ms': max(s['diagnostics']['scheduled_delay_ms']['p95'] for s,t in trials),
               'max_trial_probe_queue_p95_ms': max(s['diagnostics']['first_probe_queue_ms']['p95'] or 0 for s,t in trials),
               'errors': sum(r['status']=='error' for r in all_records),
               'timeouts': sum(r['status']=='timeout' for r in all_records)}
        for threshold in (10,50,100,1000):
            row[f'fraction_within_{threshold}ms'] = sum(r['status']=='success' and r['freshness_ms']<=threshold for r in all_records)/n
        row['all_trials_observed'] = len(trials)==experiment['arguments']['trials']
        row['arrival_schedule_pass'] = row['max_trial_schedule_p95_ms']<=1000/rate
        row['probe_resolution_pass'] = row['max_trial_probe_queue_p95_ms']<=10
        rows.append(row)
    (root/'results.json').write_text(json.dumps(rows, indent=2)+'\n')
    with (root/'results.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import LogLocator, NullFormatter, FuncFormatter
    rates = sorted({rate for backend,rate in records})
    fig, axes = plt.subplots(1,len(rates), figsize=(6*len(rates),4), squeeze=False)
    for ax, rate in zip(axes[0], rates):
        for backend in ('qdrant','weaviate','pgvector'):
            traces = records.get((backend,rate), [])
            values = sorted(r['freshness_ms'] for r in traces if r['status']=='success')
            ax.step(values, [(i+1)/len(traces) for i in range(len(values))], where='post', label=backend)
        ax.set_xscale('log'); ax.set_ylim(0,1.01)
        ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1,3)))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, pos: f'{value:g}'))
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlabel('Submission to successful response (ms)')
        ax.set_ylabel('Fraction of all submitted documents')
        ax.set_title(f'{rate:g} documents/second'); ax.grid(alpha=.2); ax.legend()
    fig.suptitle('Insert visibility: Python documentation, cached MiniLM vectors')
    fig.tight_layout(); fig.savefig(root/'freshness.svg'); fig.savefig(root/'freshness.png', dpi=180)
    lines = ['# Freshness Benchmark: insert visibility v1', '',
             'This experiment measures the first successful self-vector search response after submission. It is an observation upper bound, including client queues, transport and query time. Negative ANN probes do not establish absence.', '',
             f"Scope: local single-node Docker, Python 3.13 documentation, 384-dimensional cached MiniLM vectors, collection-wide cosine search, top-10, {experiment['arguments']['preload']:,} preloaded records, {experiment['arguments']['docs']:,} measured inserts per trial. Resource limits: 2 CPUs and 2 GiB per backend. No claim about semantic relevance, durability equivalence, distributed operation, updates/deletes, or large production indexes.", '',
             '| Backend | Docs/s | Trials | Success | Median trial p50 ms | Median trial p95 ms | 95% interval for median p95 | ≤100ms / all submissions | Schedule / probe gates |',
             '|---|---:|---:|---:|---:|---:|---|---:|---|']
    def fmt(value):
        return 'n/a' if value is None else f'{value:.2f}'
    for row in rows:
        lines.append(f"| {row['backend']} | {row['rate']:g} | {row['trials']} | {row['success_rate']:.2%} | {fmt(row['median_trial_p50_ms'])} | {fmt(row['median_trial_p95_ms'])} | [{fmt(row['p95_trial_bootstrap_95_low_ms'])}, {fmt(row['p95_trial_bootstrap_95_high_ms'])}] | {row['fraction_within_100ms']:.2%} | {row['arrival_schedule_pass']} / {row['probe_resolution_pass']} |")
    lines += ['', '![Observed freshness CDF](freshness.png)', '',
              'Intervals use 10,000 seeded bootstrap resamples of independent trial p95 values, followed by the median. Five trials give limited uncertainty resolution. CDFs pool observations descriptively; failures remain in the denominator. No significance or universal winner is asserted.', '',
              'Arrival gate: each trial’s p95 scheduling delay must be ≤ one requested interarrival interval. Probe gate: each trial’s p95 first-probe queue must be ≤10ms. A failed gate limits backend-specific interpretation; all results are retained. A successful first probe provides no estimate of visibility before that response.', '',
              f"Completed {len(progress)} of {len(experiment['order'])} planned runs. See results.csv, experiment.json, each run’s summary.json/trace.jsonl, and checksums.json for audit evidence."]
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n')
    table = '<table><thead><tr>'+''.join('<th>'+html.escape(key)+'</th>' for key in rows[0])+'</tr></thead><tbody>'
    for row in rows:
        table += '<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in row.values())+'</tr>'
    table += '</tbody></table>'
    (root/'report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Freshness Benchmark v1</title><style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#182a35}table{border-collapse:collapse;display:block;overflow:auto}td,th{padding:10px;border:1px solid #ccd;text-align:right}img{width:100%}pre{white-space:pre-wrap;line-height:1.6}</style><h1>Freshness Benchmark: insert visibility v1</h1><p>Observed latency includes client queues and transport. Read the scope and validity gates below before comparing.</p><img src="freshness.svg" alt="CDF of all submitted documents by observed freshness">'+table+'<pre>'+html.escape('\n'.join(lines))+'</pre></html>')
    checksums = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(root.rglob('*')) if p.is_file() and p.name!='checksums.json'}
    (root/'checksums.json').write_text(json.dumps(checksums, indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('directory',type=Path)
    analyze(p.parse_args().directory)
