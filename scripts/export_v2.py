#!/usr/bin/env python3
"""Build public, portable result data and compressed evidence from actual trials."""
import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import tarfile
import zipfile

from freshness_benchmark.quality import file_sha
from freshness_benchmark.reporting import percentile


def median(values):
    values=[v for v in values if v is not None]
    return statistics.median(values) if values else None


def interval(values):
    values=[v for v in values if v is not None]
    if len(values)<2:return [None,None]
    rng=random.Random(20261028)
    samples=[statistics.median(rng.choices(values,k=len(values))) for _ in range(5000)]
    return [percentile(samples,2.5),percentile(samples,97.5)]


def export(root,dest):
    dest.mkdir(parents=True,exist_ok=True);evidence=dest/'evidence';evidence.mkdir(exist_ok=True)
    # Replace only files owned by this exporter; don't carry pilot traces into a release.
    for previous in evidence.glob('fb2_*.gz'):previous.unlink()
    experiment=json.loads((root/'experiment.json').read_text())
    progress=[json.loads(line) for line in (root/'progress.jsonl').read_text().splitlines()] if (root/'progress.jsonl').exists() else []
    runs=[];buckets=defaultdict(list)
    for entry in progress:
        directory=root/'runs'/entry['run'];run={**entry,'summary':None}
        if entry['status']=='complete':
            summary=json.loads((directory/'summary.json').read_text());run['summary']=summary
            events=[json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
            run['examples']=[next((r for r in events if r['operation']==op and r['status']=='success'),None) for op in ('insert','update','delete')]
        else:
            run['failure']=json.loads((directory/'failure.json').read_text()) if (directory/'failure.json').exists() else {'error':entry.get('error')}
        runs.append(run);buckets[(entry['scenario'],entry['backend'])].append(run)
        for filename in ('summary.json','failure.json','reference.json','events.jsonl','queries.jsonl','probes.jsonl'):
            source=directory/filename
            if source.exists():
                target=evidence/f'{entry["run"]}-{filename}.gz'
                with source.open('rb') as src,target.open('wb') as output:
                    with gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=0) as gz:shutil.copyfileobj(src,gz)
    groups=[]
    for (scenario,backend),entries in sorted(buckets.items()):
        complete=[r for r in entries if r['summary']]
        for operation in ('insert','update','delete'):
            samples=[r['summary']['operations'][operation] for r in complete if operation in r['summary']['operations']]
            first=[s['first_observed_ms']['p95'] for s in samples];confirmed=[s['confirmed_ms']['p95'] for s in samples]
            total=sum(s['count'] for s in samples);success=sum(s['success'] for s in samples)
            groups.append({'scenario':scenario,'backend':backend,'operation':operation,'trials':len(complete),
                'expected_trials':experiment['arguments']['trials'],'failed_runs':len(entries)-len(complete),'events':total,'success':success,
                'success_rate':success/total if total else None,'first_p95':median(first),'first_ci':interval(first),
                'confirmed_p95':median(confirmed),'confirmed_ci':interval(confirmed),
                'query_p95':median([r['summary']['query']['latency_ms']['p95'] for r in complete]),
                'query_ci':interval([r['summary']['query']['latency_ms']['p95'] for r in complete]),
                'ann_recall':median([r['summary']['query']['ann_recall_at_10'] for r in complete]),
                'ndcg':median([r['summary']['query']['ndcg_at_10'] for r in complete]),
                'idle_query_p95':median([r['summary']['metadata']['idle_queries']['latency_ms']['p95'] for r in complete]),
                'exact_ndcg':median([r['summary']['metadata']['exact_ndcg'] for r in complete]),
                'within_100ms':sum(s['confirmed_within_100ms']*s['count'] for s in samples)/total if total else None,
                'within_1000ms':sum(s['confirmed_within_1000ms']*s['count'] for s in samples)/total if total else None,
                'regressions':sum(s['regressions'] for s in samples),
                'eligible':len(complete)==experiment['arguments']['trials'] and all(r['eligible'] for r in complete),
                'failed_gates':sorted({g for r in complete for g,ok in r['gates'].items() if not ok}),
                'run_ids':[r['run'] for r in entries]})
    calibration=json.loads((root/'calibration.json').read_text())
    reference=(experiment['arguments']['trials']==5 and experiment['arguments']['duration']==30
               and len(experiment['order'])==60)
    continuations=[]
    for directory in sorted((root/'continuations').glob('*')):
        if (directory/'continuation.json').exists():
            continuation=json.loads((directory/'continuation.json').read_text())
            if (directory/'interrupted-trial.json').exists():continuation['interrupted_attempt']=json.loads((directory/'interrupted-trial.json').read_text())
            continuations.append(continuation)
    data={'protocol':'mixed-mutations-v2','generated_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
          'completed':sum(r['status']=='complete' for r in progress),'failed':sum(r['status']=='failed' for r in progress),
          'planned':len(experiment['order']),'status':'complete' if len(progress)==len(experiment['order']) else 'running',
          'track':'reference' if reference else 'pilot',
          'experiment':experiment,'groups':groups,'runs':runs,'calibration':calibration,'continuations':continuations}
    # Local checkout paths in dependency metadata are not necessary for public reproduction.
    data['experiment']['dependencies']='\n'.join(line for line in experiment['dependencies'].splitlines() if not line.startswith('-e '))
    (dest/'results.json').write_text(json.dumps(data,indent=2)+'\n')
    (root/'results.json').write_text(json.dumps(data,indent=2)+'\n')
    with (dest/'results.csv').open('w') as f:
        columns=list(groups[0]) if groups else []
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(groups)
    shutil.copy2(dest/'results.csv',root/'results.csv')
    for dataset,manifest in experiment['datasets'].items():
        (dest/f'{dataset}-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        shutil.copy2(Path('benchmarks/data/v2')/dataset/'UPSTREAM-LICENSE.md',dest/f'{dataset}-LICENSE.md')
    # Source is small enough to download directly from the website, including the exact launch snapshot.
    shutil.copy2(root/'source.tar.gz',dest/'experiment-source.tar.gz')
    for name in ('verification.json','REPORT.md','latency-distributions.svg'):
        if (root/name).exists():shutil.copy2(root/name,dest/name)
    with zipfile.ZipFile(dest/'benchmark-source.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for directory in ('src','scripts','tests','docs','benchmarks','web','.github'):
            for path in sorted(Path(directory).rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts and 'data' not in path.parts:
                    archive.write(path)
        for name in ('README.md','methodology.md','pyproject.toml','docker-compose.v2.yml','LICENSE','CITATION.cff','CONTRIBUTING.md'):
            archive.write(name)
    # The portable evidence bundle contains the complete verifier input, including
    # calibration traces, failed setups, launch source, and every observation.
    with tarfile.open(dest/'benchmark-evidence.tar.gz','w:gz') as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.name!='checksums.json':archive.add(path,arcname='publication-v2/'+str(path.relative_to(root)))
    checksums={str(p.relative_to(dest)):file_sha(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name!='checksums.json'}
    (dest/'checksums.json').write_text(json.dumps(checksums,indent=2)+'\n')
    if data['status']=='complete':
        (root/'checksums.json').write_text(json.dumps({str(p.relative_to(root)):file_sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='checksums.json'},indent=2)+'\n')
    else:
        # Live files continue changing. Only the immutable website export has a
        # valid checksum inventory until the measurement directory is complete.
        (root/'checksums.json').unlink(missing_ok=True)
    print(f'Exported {len(progress)}/{len(experiment["order"])} cells, {len(groups)} operation comparisons')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--out',type=Path,default=Path('website/dist/data'))
    args=p.parse_args();export(args.directory,args.out)
