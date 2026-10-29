#!/usr/bin/env python3
"""Generate a publication report and failure-inclusive latency distributions."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

NAMES={'qdrant':'Qdrant','weaviate':'Weaviate','pgvector':'pgvector'}
COLORS={'qdrant':'#24627c','weaviate':'#9b6424','pgvector':'#467448'}
SCENARIOS=['scifact-small','nq-10k','nq-100k','nq-100k-burst']
TITLES=['SciFact · 4k','NQ · 10k','NQ · 100k','NQ · 100k · burst']


def generate(root):
    data=json.loads((root/'results.json').read_text())
    if data['status']!='complete' or data.get('track')!='reference':
        raise ValueError('A release report requires a complete reference matrix')
    events=defaultdict(list)
    for run in data['runs']:
        if run['status']=='complete':
            for line in (root/'runs'/run['run']/'events.jsonl').read_text().splitlines():
                event=json.loads(line);events[run['scenario'],run['backend'],event['operation']].append(event)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    fig,axes=plt.subplots(3,4,figsize=(13,8),sharex=True,sharey=True)
    for row,operation in enumerate(('insert','update','delete')):
        for col,scenario in enumerate(SCENARIOS):
            ax=axes[row,col]
            for backend in NAMES:
                subset=events[scenario,backend,operation]
                times=sorted(e['confirmed_ms'] for e in subset if e['status']=='success')
                if subset:
                    xs=[1]+times+[5000];ys=[0]+[(i+1)/len(subset) for i in range(len(times))]+[len(times)/len(subset)]
                    ax.step(xs,ys,where='post',color=COLORS[backend],linewidth=1.6,label=NAMES[backend])
            ax.set_xscale('log');ax.set_xlim(1,5000);ax.set_ylim(0,1.02)
            ax.grid(alpha=.18);ax.axvline(100,color='#888888',linestyle=':',linewidth=.7)
            ax.axvline(1000,color='#888888',linestyle=':',linewidth=.7)
            if row==0:ax.set_title(TITLES[col],loc='left',fontweight='bold')
            if col==0:ax.set_ylabel(f'{operation.capitalize()}\nFraction of all offered events')
            if row==2:ax.set_xlabel('Confirmed observation (ms)')
            limited=[NAMES[g['backend']] for g in data['groups'] if g['scenario']==scenario and g['operation']==operation and not g['eligible']]
            if limited:ax.text(.03,.08,'Limited: '+', '.join(limited),transform=ax.transAxes,fontsize=7,color='#8c3b22')
    handles,labels=axes[0,0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='upper center',ncol=3,frameon=False,bbox_to_anchor=(.5,1.0))
    fig.text(.06,.015,'Empirical distributions pool events for visualization only. Statistical intervals resample trials.\nFailures remain in the denominator. Confirmation includes a 50ms observation window; client and API costs are included.',fontsize=8,color='#555555')
    fig.tight_layout(rect=(0,.06,1,.95));fig.savefig(root/'latency-distributions.svg');fig.savefig(root/'latency-distributions.pdf');fig.savefig(root/'latency-distributions.png',dpi=160);plt.close(fig)
    total=sum(g['events'] for g in data['groups']);success=sum(g['success'] for g in data['groups'])
    lines=['# Protocol 2 reference results','',
        f"{data['completed']}/{data['planned']} planned trials completed; {data['failed']} setup failures. {total:,} offered mutations; {success:,} confirmed successfully.",'',
        'This is the single-host reference for a public benchmark protocol, not a universal product ranking. The [methodology](https://github.com/aadithya2112/freshness-benchmark/blob/v0.5.0/methodology.md) defines the clock, quality cohort, failure handling, and limits.','',
        f"Host: {data['experiment']['host']['cpu_model']}. Each container: 2 CPUs / 3 GiB. Five trials per cell, 30s admission, 10 mutations/s and 10 real-question queries/s. Burst windows offer 40 mutations/s for 1s every 10s. Observation reads add load.",'',
        '![Failure-inclusive confirmation distributions](latency-distributions.svg)','',
        '## Per-workload comparisons','',
        'Times are medians of trial p95s. Intervals are 95% bootstrap intervals over five trials. Latencies condition on successful events; success and SLO fractions use all offered mutations. “Limited” means at least one validity check failed; inspect the evidence before comparing that cell.','',
        '| Workload | Engine | Change | Events | Confirmed | First p95 [95% CI], ms | Confirmed p95 [95% CI], ms | Within 100ms | ANN recall | Validity |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---|']
    fmt=lambda value:'—' if value is None else f'{value:.2f}'
    percent=lambda value:'—' if value is None else f'{value*100:.1f}%'
    for g in data['groups']:
        lines.append(f"| {g['scenario']} | {NAMES[g['backend']]} | {g['operation']} | {g['events']} | {percent(g['success_rate'])} | {fmt(g['first_p95'])} [{fmt(g['first_ci'][0])}, {fmt(g['first_ci'][1])}] | {fmt(g['confirmed_p95'])} [{fmt(g['confirmed_ci'][0])}, {fmt(g['confirmed_ci'][1])}] | {percent(g['within_100ms'])} | {percent(g['ann_recall'])} | {'Pass' if g['eligible'] else 'Limited: '+', '.join(g['failed_gates'])} |")
    lines+=['','## Retrieval during mutations','',
        'Each trial sends 300 real-question queries to the immutable cohort in the same changing index. The idle baseline uses 100 queries before mutation admission. Times are medians of trial p95s; loaded intervals resample whole trials. ANN recall measures approximation quality, while nDCG measures agreement with relevance judgments. These are subset scores, not full BEIR scores.','',
        '| Workload | Engine | Successful queries | Idle p95, ms | Loaded p95 [95% CI], ms | ANN recall@10 | nDCG@10 | Exact nDCG@10 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for g in data['groups']:
        if g['operation']!='insert':continue
        summaries=[r['summary'] for r in data['runs'] if r['run'] in g['run_ids'] and r['summary']]
        query_count=sum(s['query']['count'] for s in summaries);query_success=sum(s['query']['success'] for s in summaries)
        lines.append(f"| {g['scenario']} | {NAMES[g['backend']]} | {query_success}/{query_count} | {fmt(g['idle_query_p95'])} | {fmt(g['query_p95'])} [{fmt(g['query_ci'][0])}, {fmt(g['query_ci'][1])}] | {percent(g['ann_recall'])} | {fmt(g['ndcg'])} | {fmt(g['exact_ndcg'])} |")
    lines+=['','## Provenance and interpretation','',
        'All trials and failed gates are preserved in `results.json`; raw traces are in the complete evidence download. The verifier reconstructs confirmations and metrics from probes and queries. The exact source at launch, data/model hashes, images, effective index configuration, CPU/throttling counters, and randomized order accompany the results.','',
        'The fixed embedding model, relevant-first subset selection, filtered immutable quality cohort, simulated disjoint-ID mutations, short trials, shared Docker host, backend-specific transports, and acknowledgement semantics bound the claims. There is no historical replay, distributed consistency test, independent external replication, or maximum-throughput measurement here.','',
        'Higher-rate diagnostic pilots and the interrupted boundary-scheduling audit are separate artifacts. They did not contribute observations to this reference matrix.']
    interruptions=[c['interrupted_attempt'] for c in data.get('continuations',[]) if 'interrupted_attempt' in c]
    if interruptions:
        lines+=['','## Continuation history','',f'{len(interruptions)} partial attempt was interrupted by the host/session and retained under `continuations/`. The first six completed trials were kept, the environment and measurement-source hashes were checked, calibration was repeated, and the partial seventh trial was restarted from a fresh collection. This interruption is excluded from database reliability statistics because it lacks a terminal measurement record. Raw partial probes and continuation metadata remain in the evidence bundle. Container restart/cache-state differences are an additional limitation.']
    for continuation in data.get('continuations',[]):
        if continuation.get('paused_checkpoint'):
            lines+=['',f"A user-requested pause followed {continuation['completed_prefix']} completed trials at a clean boundary. Containers were stopped and later restarted; environment and source checks and calibration were repeated before continuing. No completed trial was replaced."]
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(f'Wrote report and SVG/PDF distributions for {total:,} offered mutations')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);generate(p.parse_args().directory)
