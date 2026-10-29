#!/usr/bin/env python3
"""Randomized independent trials; retain every run and never overwrite evidence."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import random
import platform
import os
import subprocess
import time
import tarfile

from freshness_benchmark.config import build_parser, config_from_args
from freshness_benchmark.runner import run_benchmark


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--trials', type=int, default=5)
    p.add_argument('--docs', type=int, default=1000)
    p.add_argument('--preload', type=int, default=2000)
    p.add_argument('--rates', type=float, nargs='+', default=[50, 200])
    p.add_argument('--seed', type=int, default=20261028)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    data = Path('benchmarks/data/python-docs')
    base = config_from_args(build_parser().parse_args([
        'run', '--workload', 'dataset', '--dataset-path', str(data/'corpus.jsonl'),
        '--dataset-format', 'jsonl', '--text-field', 'body', '--id-field', 'doc_id',
        '--embedding-cache', str(data/'embeddings.json'), '--embedding-dimensions', '384',
        '--search-scope', 'collection', '--no-anchor', '--poll-interval-ms', '10',
        '--max-wait-s', '10', '--docs', str(args.docs), '--preload-docs', str(args.preload)]))
    cells = [(trial, backend, rate) for trial in range(args.trials)
             for backend in ('qdrant','weaviate','pgvector') for rate in args.rates]
    random.Random(args.seed).shuffle(cells)
    metadata = {'host': {'platform': platform.platform(), 'cpu_count': os.cpu_count(),
                         'cpu_model': subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'], text=True).strip() if platform.system()=='Darwin' else platform.processor(),
                         'memory_bytes': os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')},
                'protocol': 'insert-self-vector-v1', 'arguments': vars(args), 'order': cells,
                'dataset': json.loads((data/'manifest.json').read_text()),
                'dependencies': subprocess.check_output(['uv','pip','freeze','--python','.venv/bin/python'], text=True),
                'docker': json.loads(subprocess.check_output(['docker','inspect','freshness-qdrant','freshness-weaviate','freshness-pgvector'], text=True))}
    # Docker inspect is local infrastructure metadata; remove arbitrary environment values.
    for container in metadata['docker']:
        container['Config'].pop('Env', None)
    (out/'experiment.json').write_text(json.dumps(metadata, indent=2))
    with tarfile.open(out/'source.tar.gz', 'w:gz') as archive:
        for directory in ('src', 'scripts', 'tests'):
            for path in sorted(Path(directory).rglob('*.py')):
                archive.add(path)
        for path in ('pyproject.toml','docker-compose.yml','benchmarks/python-docs.lock.json'):
            archive.add(path)
    for index, (trial, backend, rate) in enumerate(cells):
        name = f'pub_{out.name}_{index:02d}'.replace('-', '_')
        cfg = replace(base, run_id=name, collection=name, backend=backend, rate=rate,
                      out_dir=str(out/'runs'/name))
        print(f'CELL {index+1}/{len(cells)} trial={trial+1} backend={backend} rate={rate}', flush=True)
        summary = run_benchmark(cfg)
        with (out/'progress.jsonl').open('a') as f:
            f.write(json.dumps({'trial': trial+1, 'backend': backend, 'rate': rate,
                                'run_dir': cfg.out_dir, 'success_rate': summary.success_rate})+'\n')
        time.sleep(1)
    print('Experiment complete', flush=True)


if __name__ == '__main__':
    main()
