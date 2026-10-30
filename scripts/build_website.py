#!/usr/bin/env python3
"""Build the Astro website while preserving existing frozen evidence downloads."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from export_v2 import export

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('experiment', type=Path)
    parser.add_argument('--out', type=Path, default=Path('website/dist'))
    args = parser.parse_args()
    output = args.out.resolve()
    if output == Path.cwd() or output in Path.cwd().parents:
        parser.error('Output must be a dedicated build directory')
    output.mkdir(parents=True, exist_ok=True)
    results = args.experiment / 'results.json'
    evidence_results = output / 'data/results.json'
    if not results.exists() or not evidence_results.exists():
        export(args.experiment, output / 'data')
    else:
        expected = json.loads(results.read_text())
        existing = json.loads(evidence_results.read_text())
        identity = lambda data: (data['protocol'], [(r['run'], r['status']) for r in data['runs']])
        if identity(expected) != identity(existing):
            export(args.experiment, output / 'data')
    environment = {**os.environ, 'FRESHNESS_RESULTS_FILE': str(results.resolve())}
    subprocess.run(['npm', 'run', 'build', '--prefix', 'web'], env=environment, check=True)
    for child in output.iterdir():
        if child.name == 'data':
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree('web/dist', output, dirs_exist_ok=True)
    print(f'Astro website built at {output}; evidence downloads preserved')
